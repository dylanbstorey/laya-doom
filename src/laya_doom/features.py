"""The numeric view of an Observation, for a distilled student.

A student that read the state *text* would pay the same encoding cost that makes
LAYA slow, which defeats the point. So the student reads this fixed-width vector
instead, built from the same Observation the text is written from.

That is also the honest limit of the exercise: a model over engineered features
is learning features -> action, and `ScriptedClient` is exactly such a mapping,
written by hand. Distillation is only worth doing where LAYA's mapping beats the
one a person would write -- which is what `bench/gate.py` measures first.

Everything is scaled to roughly [0, 1] so a small network trains without a
separate normalisation pass, and every feature is derivable on a live tick with
no extra work: these are the numbers `state.py` already computed to write its
sentences.
"""

from __future__ import annotations

from .state import DISTANCE_BANDS, WEAPON_NAMES, Observation

MAX_WEAPON_SLOT = 7
ITEM_KINDS = ("health", "ammunition", "weapon")
ITEM_RANGE = 800.0     # beyond this a pickup is not worth describing
DISTANCE_RANGE = 1400.0  # deadly_corridor's sightlines reach ~1330

FEATURE_NAMES: list[str] = [
    "health",
    "ammo",
    "armor",
    "armor_known",
    "enemies_in_sight",
    "any_enemy_lined_up",
    "nearest_present",
    "nearest_offset",          # signed, negative is left
    "nearest_offset_abs",
    "nearest_is_left",
    "nearest_is_right",
    "nearest_in_crosshair",
    "nearest_distance",
    *[f"nearest_band_{index}" for index in range(len(DISTANCE_BANDS) + 1)],
    "second_present",
    "second_offset",
    "second_distance",
    "incoming_projectiles",
    "progress",
    "has_goal",
    "weapon_ammo",
    *[f"weapon_slot_{slot}" for slot in range(1, MAX_WEAPON_SLOT + 1)],
    *[f"{kind}_pickup_present" for kind in ITEM_KINDS],
    *[f"{kind}_pickup_distance" for kind in ITEM_KINDS],
]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _distance_band(distance: float) -> list[float]:
    """One-hot over the same bands the narration uses, so the student sees the
    discretisation the teacher was reasoning about, not just the raw number."""
    onehot = [0.0] * (len(DISTANCE_BANDS) + 1)
    for index, (limit, _phrase) in enumerate(DISTANCE_BANDS):
        if distance < limit:
            onehot[index] = 1.0
            return onehot
    onehot[-1] = 1.0
    return onehot


def features(observation: Observation) -> list[float]:
    """Observation -> fixed-width vector, in FEATURE_NAMES order."""
    nearest = observation.nearest
    second = observation.enemies[1] if len(observation.enemies) > 1 else None

    row: list[float] = [
        _clamp(observation.health / 100.0),
        _clamp(observation.ammo / 50.0),
        _clamp((observation.armor or 0.0) / 100.0),
        1.0 if observation.armor is not None else 0.0,
        _clamp(len(observation.enemies) / 3.0),
        1.0 if observation.crosshair_target is not None else 0.0,
    ]

    if nearest is None:
        row += [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] + [0.0] * (len(DISTANCE_BANDS) + 1)
    else:
        row += [
            1.0,
            _clamp(nearest.offset_fraction, -1.0, 1.0),
            _clamp(abs(nearest.offset_fraction)),
            1.0 if nearest.offset < 0 else 0.0,
            1.0 if nearest.offset > 0 else 0.0,
            1.0 if nearest.in_crosshair else 0.0,
            _clamp(nearest.distance / DISTANCE_RANGE),
        ] + _distance_band(nearest.distance)

    row += [
        1.0 if second is not None else 0.0,
        _clamp(second.offset_fraction, -1.0, 1.0) if second else 0.0,
        _clamp(second.distance / DISTANCE_RANGE) if second else 0.0,
        _clamp(observation.incoming_projectiles / 3.0),
        observation.progress if observation.progress is not None else 0.0,
        1.0 if observation.has_goal else 0.0,
        _clamp((observation.weapon_ammo or 0.0) / 50.0),
    ]

    slot = int(observation.weapon_slot or 0)
    row += [1.0 if slot == index else 0.0 for index in range(1, MAX_WEAPON_SLOT + 1)]

    distances = [observation.nearest_item(kind) for kind in ITEM_KINDS]
    row += [1.0 if distance is not None else 0.0 for distance in distances]
    row += [_clamp(distance / ITEM_RANGE) if distance is not None else 1.0 for distance in distances]

    assert len(row) == len(FEATURE_NAMES), f"{len(row)} values for {len(FEATURE_NAMES)} names"
    return row


def features_from_state(state: dict) -> list[float]:
    """Rebuild the vector from a serialized state dict.

    Harvested rows store the dict that was posted to the model, not the
    Observation it came from, so training reads through here. Kept deliberately
    close to `features` -- anything it cannot recover is a sign the state text
    carries something the student is not being shown.
    """
    from .state import Observation as _Observation  # local import keeps the module light

    nearest = state.get("nearest_enemy") or {}
    where = str(nearest.get("where", ""))
    lined_up = bool(state.get("an_enemy_is_lined_up_with_your_crosshair"))

    # Reconstruct just enough of an Observation for the shared code path.
    class _Sighting:
        def __init__(self) -> None:
            self.offset_fraction = -0.5 if "left" in where else 0.5 if "right" in where else 0.0
            self.offset = -1 if "left" in where else 1 if "right" in where else 0
            self.in_crosshair = bool(nearest.get("lined_up_with_crosshair"))
            self.distance = _distance_from_phrase(str(nearest.get("how_far", "")))

    sightings = tuple([_Sighting()] * min(int(state.get("enemies_in_sight", 0)), 3)) if nearest else ()
    observation = _Observation(
        health=float(state.get("health", 0)),
        ammo=float(state.get("ammunition", 0)),
        enemies=sightings,
        progress=(state.get("percent_of_the_way_to_the_goal", None) or 0) / 100.0
        if "percent_of_the_way_to_the_goal" in state else None,
        armor=float(state["armour"]) if "armour" in state else None,
        weapon_slot=_slot_from_name(state.get("weapon_in_hand")),
        weapon_ammo=float(state.get("shots_left_for_this_weapon", 0)),
        items=tuple(
            (kind, float(state[f"nearest_{kind}_pickup_distance"]))
            for kind in ITEM_KINDS
            if f"nearest_{kind}_pickup_distance" in state
        ),
    )
    row = features(observation)
    # `crosshair_target` cannot be recovered from the reconstructed sightings, so
    # take the flag the state states outright.
    row[FEATURE_NAMES.index("any_enemy_lined_up")] = 1.0 if lined_up else 0.0
    return row


def _distance_from_phrase(phrase: str) -> float:
    """Midpoint of the band a phrase names -- the student sees the band anyway."""
    for limit, band in DISTANCE_BANDS:
        if band == phrase:
            return limit * 0.75
    return DISTANCE_RANGE * 0.8


def _slot_from_name(name: str | None) -> int | None:
    if not name:
        return None
    for slot, label in WEAPON_NAMES.items():
        if label == name:
            return slot
    return None
