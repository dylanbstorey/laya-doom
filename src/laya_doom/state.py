"""ViZDoom game state -> the compact dict LAYA reads.

This is the highest-leverage file in the project. Discovery established that
answer quality is dominated by *state phrasing*, not question wording: the same
`turn` question scored confidence 0.0115 when the state said "bearing +6 degrees
right" and 0.228 (and correct) when it said "slightly LEFT of your crosshair".

So the rule this module follows, and the line the project's "the model decides,
the code does not" principle draws:

    Python computes the observation. LAYA chooses the action.

Bearing words, distance words and crosshair alignment are all *observations* --
the same job the reference pong demo does when it computes "above / below /
aligned" in JavaScript. What to do about them is left entirely to the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

# Doom actors that are monsters. An allowlist rather than "everything that is not
# the player", because the label buffer also reports blood splatter, bullet puffs,
# corpses and pickups -- captured fixtures contain Blood, BulletPuff, TeleportFog,
# Medikit, Clip, GreenArmor and DeadZombieman. Treating those as enemies would
# have the model shooting at its own bullet holes.
MONSTERS = frozenset({
    "Zombieman", "ShotgunGuy", "ChaingunGuy", "DoomImp", "Demon", "Spectre",
    "Cacodemon", "BaronOfHell", "HellKnight", "LostSoul", "PainElemental",
    "Revenant", "Fatso", "Mancubus", "Arachnotron", "Archvile", "Cyberdemon",
    "SpiderMastermind", "WolfensteinSS",
})

# ViZDoom ships custom marine actors whose names vary by scenario
# (MarineChainsawVzd and friends).
MONSTER_PREFIXES = ("Marine",)

PROJECTILES = frozenset({"DoomImpBall", "CacodemonBall", "BaronBall", "RevenantTracer", "ArachnotronPlasma", "Rocket"})

# Pickups worth naming, by what they are for. deathmatch's label buffer is mostly
# these -- RocketBox, ShellBox, CellPack, Medikit, Stimpack, ClipBox and weapons --
# so a state that only describes monsters throws away most of what is on screen.
HEALTH_ITEMS = frozenset({"Medikit", "Stimpack", "HealthBonus", "Soulsphere", "Megasphere"})
ARMOR_ITEMS = frozenset({"GreenArmor", "BlueArmor", "ArmorBonus", "Megasphere"})
AMMO_ITEMS = frozenset({"Clip", "ClipBox", "Shell", "ShellBox", "RocketAmmo", "RocketBox", "Cell", "CellPack"})
WEAPON_ITEMS = frozenset({
    "Shotgun", "SuperShotgun", "Chaingun", "RocketLauncher", "PlasmaRifle", "BFG9000", "Chainsaw",
})

# Doom's weapon slots, as SELECTED_WEAPON reports them.
WEAPON_NAMES = {
    1: "fist or chainsaw", 2: "pistol", 3: "shotgun", 4: "chaingun",
    5: "rocket launcher", 6: "plasma rifle", 7: "BFG",
}

SELF = "DoomPlayer"

# Plain words for the model. The checkpoint was trained on support tickets and
# invoices; engine identifiers like "MarineChainsawVzd" are out-of-distribution noise.
PLAIN_NAMES = {
    "Zombieman": "a zombie soldier", "ShotgunGuy": "a shotgun soldier",
    "ChaingunGuy": "a chaingun soldier", "DoomImp": "an imp", "Demon": "a demon",
    "Spectre": "a spectre", "Cacodemon": "a cacodemon", "BaronOfHell": "a baron of hell",
    "HellKnight": "a hell knight", "LostSoul": "a lost soul", "Revenant": "a revenant",
    "Fatso": "a mancubus", "Mancubus": "a mancubus", "Arachnotron": "an arachnotron",
    "Archvile": "an arch-vile", "Cyberdemon": "a cyberdemon",
    "SpiderMastermind": "a spider mastermind", "WolfensteinSS": "an SS soldier",
    "PainElemental": "a pain elemental",
}

# Calibrated against captured fixtures: defend_the_center sightings run 24 to 812
# world units (p50 672); deadly_corridor reaches 1328.
DISTANCE_BANDS = ((150, "right on top of you"), (350, "close"), (650, "a moderate distance away"))
FAR = "far away"

# Fractions of half-screen-width. With Doom's 90 degree FOV, half-width is 45
# degrees, so "slightly" is about 9 degrees off centre.
BEARING_BANDS = ((0.20, "slightly {side}"), (0.55, "to the {side}"))
FAR_BEARING = "far to the {side}"

MAX_ENEMIES_DESCRIBED = 3

# Widens the crosshair box when deciding whether an enemy is "lined up". 0 is the
# geometrically exact answer for a point crosshair; a few pixels of slack makes the
# model commit to a shot slightly before the sweep is perfect, which matters
# because the crosshair sits on an enemy in only ~6% of ticks.
CROSSHAIR_TOLERANCE_PX = 0


def item_kind(name: str) -> str | None:
    """What a pickup is for, or None if it is not a pickup."""
    if name in HEALTH_ITEMS:
        return "health"
    if name in ARMOR_ITEMS:
        return "armor"
    if name in AMMO_ITEMS:
        return "ammunition"
    if name in WEAPON_ITEMS:
        return "weapon"
    return None


def is_monster(name: str) -> bool:
    """True for actors that can be shot at.

    Corpses are named ``Dead*`` in Doom and are excluded: they are scenery, and
    aiming at them wastes the whole point of the decision.
    """
    if name.startswith("Dead"):
        return False
    return name in MONSTERS or name.startswith(MONSTER_PREFIXES)


def plain_name(name: str) -> str:
    if name in PLAIN_NAMES:
        return PLAIN_NAMES[name]
    if name.startswith("Marine"):
        return "a marine"
    return "an enemy"


@dataclass(frozen=True)
class EnemySighting:
    """One visible monster, already reduced to what the model needs."""

    name: str
    offset: int          # pixels from screen centre; negative is left
    offset_fraction: float
    distance: float
    in_crosshair: bool   # the crosshair falls inside this enemy's bounding box

    @property
    def side(self) -> str:
        return "left" if self.offset < 0 else "right"

    @property
    def bearing_phrase(self) -> str:
        if self.in_crosshair:
            return "centred in your crosshair"
        magnitude = abs(self.offset_fraction)
        for limit, template in BEARING_BANDS:
            if magnitude <= limit:
                return template.format(side=self.side)
        return FAR_BEARING.format(side=self.side)

    @property
    def distance_phrase(self) -> str:
        for limit, phrase in DISTANCE_BANDS:
            if self.distance < limit:
                return phrase
        return FAR

    def describe(self) -> str:
        return f"{plain_name(self.name)} is {self.bearing_phrase}, {self.distance_phrase}"

    def describe_as_subject(self) -> str:
        """Same facts, phrased to follow "The nearest enemy is ..."."""
        return f"{plain_name(self.name)}, {self.bearing_phrase}, {self.distance_phrase}"


@dataclass(frozen=True)
class Observation:
    """Everything one tick contributes, independent of ViZDoom's object model.

    Built either from a live ``GameState`` or from a recorded fixture, so tests
    and the question bench never need a Doom process.
    """

    health: float
    ammo: float
    enemies: tuple[EnemySighting, ...]
    killcount: float = 0.0
    screen_width: int = 320
    incoming_projectiles: int = 0
    # Maps with a destination (deadly_corridor's vest at x=1312) report how far
    # along it the player is. None on maps that are not going anywhere.
    progress: float | None = None
    distance_to_goal: float | None = None
    # deathmatch only: armour, the weapon in hand, and what is lying around.
    armor: float | None = None
    weapon_slot: int | None = None
    weapon_ammo: float | None = None
    weapons_held: tuple[int, ...] = ()          # slots the player is carrying
    items: tuple[tuple[str, float], ...] = ()   # (kind, distance), nearest first

    @property
    def weapon_name(self) -> str:
        return WEAPON_NAMES.get(int(self.weapon_slot or 0), "an unknown weapon")

    def nearest_item(self, kind: str) -> float | None:
        return next((distance for k, distance in self.items if k == kind), None)

    @property
    def weapon_names_held(self) -> list[str]:
        return [WEAPON_NAMES[slot] for slot in self.weapons_held if slot in WEAPON_NAMES]

    @property
    def nearest(self) -> EnemySighting | None:
        return self.enemies[0] if self.enemies else None

    @property
    def has_goal(self) -> bool:
        return self.progress is not None

    @property
    def crosshair_target(self) -> EnemySighting | None:
        """The nearest enemy the crosshair is actually on, if any.

        Distinct from ``nearest``: a fixture exists where the closest demon is
        far to the left while a marine further away sits dead centre. Firing
        depends on this one, aiming depends on ``nearest``, and conflating them
        made the narration contradict itself.
        """
        return next((enemy for enemy in self.enemies if enemy.in_crosshair), None)


def _sighting(
    label: dict,
    player: tuple[float, float],
    centre_x: float,
    half_width: float,
    tolerance_px: int = CROSSHAIR_TOLERANCE_PX,
) -> EnemySighting:
    x, y, width, _height = label["bbox"]
    box_centre = x + width / 2
    offset = box_centre - centre_x
    return EnemySighting(
        name=label["name"],
        offset=int(round(offset)),
        offset_fraction=offset / half_width if half_width else 0.0,
        distance=math.dist((label["x"], label["y"]), player),
        # Exact for hitscan weapons at tolerance 0: the shot lands where the
        # crosshair is, so the enemy is lined up precisely when the crosshair is
        # inside its box. Tolerance widens that box -- see CROSSHAIR_TOLERANCE_PX.
        in_crosshair=(x - tolerance_px) <= centre_x <= (x + width + tolerance_px),
    )


def observe(
    labels: Iterable[dict],
    *,
    health: float,
    ammo: float,
    killcount: float = 0.0,
    screen_width: int = 320,
    player: tuple[float, float] | None = None,
    max_enemies: int = MAX_ENEMIES_DESCRIBED,
    tolerance_px: int = CROSSHAIR_TOLERANCE_PX,
    goal_x: float | None = None,
    position_x: float | None = None,
    armor: float | None = None,
    weapon_slot: int | None = None,
    weapon_ammo: float | None = None,
    weapons_held: tuple[int, ...] = (),
) -> Observation:
    """Build an ``Observation`` from label dicts (live or recorded)."""
    labels = list(labels)
    if player is None:
        own = next((label for label in labels if label["name"] == SELF), None)
        player = (own["x"], own["y"]) if own else (0.0, 0.0)

    centre_x = screen_width / 2
    half_width = screen_width / 2
    enemies = [
        _sighting(label, player, centre_x, half_width, tolerance_px)
        for label in labels
        if is_monster(label["name"])
    ]
    enemies.sort(key=lambda sighting: sighting.distance)
    projectiles = sum(1 for label in labels if label["name"] in PROJECTILES)

    items = sorted(
        (
            (kind, math.dist((label["x"], label["y"]), player))
            for label in labels
            if (kind := item_kind(label["name"])) is not None
        ),
        key=lambda pair: pair[1],
    )

    progress = distance_to_goal = None
    if goal_x is not None and position_x is not None and goal_x:
        progress = max(0.0, min(1.0, position_x / goal_x))
        distance_to_goal = max(0.0, goal_x - position_x)

    return Observation(
        health=health,
        ammo=ammo,
        enemies=tuple(enemies[:max_enemies]),
        killcount=killcount,
        screen_width=screen_width,
        incoming_projectiles=projectiles,
        progress=progress,
        distance_to_goal=distance_to_goal,
        armor=armor,
        weapon_slot=weapon_slot,
        weapon_ammo=weapon_ammo,
        weapons_held=tuple(weapons_held),
        items=tuple(items[:6]),
    )


def from_game_state(
    state: Any,
    game: Any,
    *,
    max_enemies: int = MAX_ENEMIES_DESCRIBED,
    tolerance_px: int = CROSSHAIR_TOLERANCE_PX,
    goal_x: float | None = None,
) -> Observation | None:
    """Adapt a live ViZDoom ``GameState``. Returns ``None`` when the episode ended."""
    if state is None:
        return None
    variables = {
        str(name).split(".")[-1]: float(value)
        for name, value in zip(game.get_available_game_variables(), state.game_variables)
    }
    labels = [
        {
            "name": label.object_name,
            "x": float(label.object_position_x),
            "y": float(label.object_position_y),
            "bbox": [int(label.x), int(label.y), int(label.width), int(label.height)],
        }
        for label in (state.labels or [])
    ]
    return observe(
        labels,
        health=variables.get("HEALTH", 0.0),
        ammo=variables.get("AMMO2", 0.0),
        killcount=variables.get("KILLCOUNT", 0.0),
        screen_width=game.get_screen_width(),
        player=(variables.get("POSITION_X", 0.0), variables.get("POSITION_Y", 0.0)) if "POSITION_X" in variables else None,
        max_enemies=max_enemies,
        tolerance_px=tolerance_px,
        goal_x=goal_x,
        position_x=variables.get("POSITION_X"),
        armor=variables.get("ARMOR"),
        weapon_slot=int(variables["SELECTED_WEAPON"]) if "SELECTED_WEAPON" in variables else None,
        weapon_ammo=variables.get("SELECTED_WEAPON_AMMO"),
        weapons_held=tuple(
            slot for slot in range(1, 8) if variables.get(f"WEAPON{slot}", 0) > 0
        ),
    )


def from_fixture(
    fixture: dict,
    *,
    max_enemies: int = MAX_ENEMIES_DESCRIBED,
    tolerance_px: int = CROSSHAIR_TOLERANCE_PX,
) -> Observation:
    """Adapt a fixture recorded by ``bench/capture.py``."""
    variables = fixture.get("game_variables", {})
    return observe(
        fixture["labels"],
        health=variables.get("HEALTH", 0.0),
        ammo=variables.get("AMMO2", 0.0),
        killcount=variables.get("KILLCOUNT", 0.0),
        screen_width=fixture.get("screen_width", 320),
        max_enemies=max_enemies,
        tolerance_px=tolerance_px,
    )


def journey_phrase(observation: Observation) -> str:
    """How far along the map's goal the player is, in words.

    Percentages are the one number this model reads reliably here, so the phrase
    carries both the plain-language distance and the figure.
    """
    if not observation.has_goal:
        return ""
    remaining = observation.distance_to_goal or 0.0
    if remaining < 120:
        how_far = "almost there"
    elif remaining < 400:
        how_far = "not much further"
    elif remaining < 800:
        how_far = "still a long way off"
    else:
        how_far = "a very long way off"
    return (
        f"The green vest at the end of the corridor is {how_far}: you are "
        f"{observation.progress * 100:.0f}% of the way there."
    )


def loadout_sentences(observation: Observation) -> list[str]:
    """What the player is holding, and what is worth picking up.

    Only says something when the map tracks weapons at all, so the other two
    scenarios' state text is unchanged.
    """
    if observation.weapon_slot is None:
        return []

    others = [name for name in observation.weapon_names_held if name != observation.weapon_name]
    if not others:
        # Nothing to decide, so nothing to say. Measured: the player held a pistol
        # and nothing else in 100% of 1436 harvested ticks, so this text was pure
        # cost -- and the deathmatch prompt runs right at the 512-token formatting
        # limit, where ~115 chars of dead weight is what tips it into a 422.
        said: list[str] = []
    else:
        said = [
            f"You are holding the {observation.weapon_name} with "
            f"{int(observation.weapon_ammo or 0)} shots left.",
            f"You are also carrying: {', '.join(others)}.",
        ]
    if (observation.weapon_ammo or 0) <= 5:
        distance = observation.nearest_item("ammunition")
        said.append(
            "You are nearly out of ammunition for it, and an ammunition pickup is nearby."
            if distance is not None and distance < 400
            else "You are nearly out of ammunition for it."
        )
    if observation.health <= 50:
        distance = observation.nearest_item("health")
        if distance is not None and distance < 400:
            said.append("There is a health pickup nearby.")
    distance = observation.nearest_item("weapon")
    if distance is not None and distance < 250:
        said.append("There is a better weapon lying close by.")
    return said


def narrate(observation: Observation) -> str:
    """The sentence that does the work.

    Mirrors the reference pong demo's ``observation`` field: the spatial relation
    stated in plain words, because that is the form this model can act on.
    """
    nearest = observation.nearest
    journey = journey_phrase(observation)

    if nearest is None:
        if observation.has_goal:
            # On a map with somewhere to be, an empty view means the way is clear.
            empty = f"{journey} No enemy is in sight, so the way ahead is clear."
        else:
            # Phrased so that searching is the obviously available move. The previous
            # wording ("your crosshair is on empty space") described the situation
            # without suggesting that anything could be done about it, and the model
            # sat still -- which was the single biggest drag on its play.
            # Kept to two sentences: the first draft ran to four and pushed decision
            # latency from 46 ms to 74 ms, which cost skipped slots at the live cadence.
            # Every token in the state is paid for on every tick.
            empty = (
                "No enemy is in sight. Enemies are approaching from outside your view, "
                "and turning to sweep the room is the only way to find them."
            )
        # The loadout belongs here too. Returning early meant that on deathmatch --
        # where the view is empty much of the time -- the prose never mentioned which
        # weapon was in hand, exactly when the weapon question was being asked.
        return " ".join([empty, *loadout_sentences(observation)])

    sentences = [f"The nearest enemy is {nearest.describe_as_subject()}."]
    target = observation.crosshair_target
    if target is nearest:
        sentences.append("It is lined up with your crosshair, so shooting now would hit it.")
    elif target is not None:
        sentences.append(
            f"It is not lined up with your crosshair, but {plain_name(target.name)} further away is "
            "centred in your crosshair, so shooting now would hit that one."
        )
    else:
        sentences.append(
            "No enemy is lined up with your crosshair; the nearest one sits to the "
            f"{nearest.side} of where you are aiming."
        )

    others = observation.enemies[1:]
    if others:
        described = "; ".join(other.describe() for other in others)
        sentences.append(f"{len(others)} more enemy in sight: {described}." if len(others) == 1
                         else f"{len(others)} more enemies in sight: {described}.")
    if observation.incoming_projectiles:
        sentences.append(f"{observation.incoming_projectiles} enemy projectile is heading toward you."
                         if observation.incoming_projectiles == 1
                         else f"{observation.incoming_projectiles} enemy projectiles are heading toward you.")
    if observation.health <= 30:
        sentences.append("You are badly hurt.")
    if observation.ammo <= 0:
        sentences.append("You are out of ammunition and cannot shoot.")
    sentences.extend(loadout_sentences(observation))
    if journey:
        sentences.append(journey)
    return " ".join(sentences)


def serialize(observation: Observation) -> dict:
    """The state dict posted to LAYA.

    Natural-language ``observation`` first, structured numbers beside it -- the
    shape the reference pong demo uses. Kept small: the typed-decisions context
    is 1024 tokens and every token is latency.
    """
    nearest = observation.nearest
    state: dict[str, Any] = {
        "observation": narrate(observation),
        "health": int(observation.health),
        "ammunition": int(observation.ammo),
        "enemies_in_sight": len(observation.enemies),
        "an_enemy_is_lined_up_with_your_crosshair": observation.crosshair_target is not None,
    }
    if observation.has_goal:
        state["percent_of_the_way_to_the_goal"] = round(observation.progress * 100)
    if observation.weapon_slot is not None:
        # The structured fields stay -- they cost ~7 tokens and a student needs them
        # to know what is in hand. It is the *prose* that was expensive, and it only
        # appears when there is actually a weapon choice to make.
        state["weapon_in_hand"] = observation.weapon_name
        state["shots_left_for_this_weapon"] = int(observation.weapon_ammo or 0)
        others = [name for name in observation.weapon_names_held if name != observation.weapon_name]
        if others:
            state["other_weapons_you_are_carrying"] = others
    if observation.armor is not None:
        state["armour"] = int(observation.armor)
    for kind in ("health", "ammunition", "weapon"):
        distance = observation.nearest_item(kind)
        if distance is not None:
            state[f"nearest_{kind}_pickup_distance"] = round(distance)
    if nearest is not None:
        state["nearest_enemy"] = {
            "what": plain_name(nearest.name),
            "where": nearest.bearing_phrase,
            "how_far": nearest.distance_phrase,
            "lined_up_with_crosshair": nearest.in_crosshair,
        }
    return state
