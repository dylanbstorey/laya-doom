"""The numeric view a distilled student would read."""

from __future__ import annotations

import pytest

from laya_doom.features import FEATURE_NAMES, features, features_from_state
from laya_doom.state import observe, serialize


def label(name: str, *, bbox=(150, 100, 20, 40), x=300.0, y=0.0) -> dict:
    return {"name": name, "x": x, "y": y, "bbox": list(bbox)}


def observation(*labels, **kwargs):
    kwargs.setdefault("health", 100.0)
    kwargs.setdefault("ammo", 26.0)
    kwargs.setdefault("player", (0.0, 0.0))
    return observe(labels, **kwargs)


def named(row: list[float]) -> dict[str, float]:
    return dict(zip(FEATURE_NAMES, row))


class TestShapeAndRange:
    def test_width_matches_the_names(self):
        assert len(features(observation(label("Demon")))) == len(FEATURE_NAMES)

    def test_width_is_the_same_with_and_without_enemies(self):
        """A fixed-width vector is the whole point; a student cannot take ragged input."""
        assert len(features(observation())) == len(features(observation(label("Demon"))))

    @pytest.mark.parametrize("obs_args", [
        {},
        {"health": 0.0, "ammo": 0.0},
        {"health": 100.0, "ammo": 999.0},
    ])
    def test_every_value_stays_in_range(self, obs_args):
        for value in features(observation(label("Demon"), **obs_args)):
            assert -1.0 <= value <= 1.0

    def test_no_nan_without_a_goal_or_weapon(self):
        row = features(observation(label("Demon")))
        assert all(value == value for value in row)  # NaN != NaN
        assert named(row)["has_goal"] == 0.0


class TestSemantics:
    def test_bearing_sign_survives(self):
        """The sign that inverts aim if wrong -- pinned here as it is in state."""
        left = named(features(observation(label("Demon", bbox=(60, 0, 20, 40)))))
        right = named(features(observation(label("Demon", bbox=(240, 0, 20, 40)))))
        assert left["nearest_offset"] < 0 < right["nearest_offset"]
        assert left["nearest_is_left"] == 1.0 and right["nearest_is_right"] == 1.0

    def test_lined_up_is_visible(self):
        row = named(features(observation(label("Demon", bbox=(150, 0, 20, 40)))))
        assert row["any_enemy_lined_up"] == 1.0
        assert row["nearest_in_crosshair"] == 1.0

    def test_distance_band_is_one_hot(self):
        row = named(features(observation(label("Demon", x=80.0))))
        bands = [row[name] for name in FEATURE_NAMES if name.startswith("nearest_band_")]
        assert sum(bands) == 1.0

    def test_no_enemy_zeroes_the_enemy_block(self):
        row = named(features(observation(label("Blood"))))
        assert row["nearest_present"] == 0.0
        assert row["enemies_in_sight"] == 0.0

    def test_weapon_slot_is_one_hot(self):
        row = named(features(observation(label("Demon"), weapon_slot=4, weapon_ammo=30.0)))
        slots = [row[name] for name in FEATURE_NAMES if name.startswith("weapon_slot_")]
        assert sum(slots) == 1.0
        assert row["weapon_slot_4"] == 1.0

    def test_goal_progress_comes_through(self):
        row = named(features(observation(label("Demon"), goal_x=1312.0, position_x=656.0)))
        assert row["progress"] == pytest.approx(0.5)
        assert row["has_goal"] == 1.0


class TestRoundTripFromSerializedState:
    """Harvested rows store the posted state dict, so training reads through
    `features_from_state`. The fields that drive the action must survive."""

    def test_the_decisive_flags_survive_the_round_trip(self):
        obs = observation(label("Demon", bbox=(150, 0, 20, 40), x=200.0))
        recovered = named(features_from_state(serialize(obs)))
        direct = named(features(obs))
        for key in ("any_enemy_lined_up", "nearest_present", "nearest_in_crosshair",
                    "nearest_is_left", "nearest_is_right", "health", "ammo"):
            assert recovered[key] == direct[key], key

    def test_an_empty_view_round_trips(self):
        recovered = named(features_from_state(serialize(observation(label("Blood")))))
        assert recovered["nearest_present"] == 0.0
        assert recovered["any_enemy_lined_up"] == 0.0

    def test_corridor_progress_round_trips(self):
        obs = observation(label("Zombieman"), goal_x=1312.0, position_x=984.0)
        assert named(features_from_state(serialize(obs)))["progress"] == pytest.approx(0.75, abs=0.01)

    def test_deathmatch_loadout_round_trips(self):
        obs = observation(label("Zombieman"), weapon_slot=3, weapon_ammo=20.0, armor=50.0)
        recovered = named(features_from_state(serialize(obs)))
        assert recovered["weapon_slot_3"] == 1.0
        assert recovered["weapon_ammo"] == pytest.approx(0.4)
        assert recovered["armor"] == pytest.approx(0.5)

    def test_width_is_identical_both_ways(self):
        obs = observation(label("Demon"))
        assert len(features_from_state(serialize(obs))) == len(features(obs))


class TestLoadoutNarration:
    """The weapon question is asked on every tick, including when nothing is
    visible -- so the prose has to describe the loadout on every tick too."""

    def test_loadout_appears_with_no_enemy_in_sight(self):
        from laya_doom.state import narrate

        text = narrate(observation(label("Blood"), weapon_slot=4, weapon_ammo=30.0,
                                   weapons_held=(2, 3, 4)))
        assert "chaingun" in text
        assert "also carrying" in text

    def test_loadout_appears_with_an_enemy_in_sight(self):
        from laya_doom.state import narrate

        text = narrate(observation(label("Zombieman"), weapon_slot=3, weapon_ammo=8.0,
                                   weapons_held=(2, 3)))
        assert "shotgun" in text

    def test_a_single_weapon_says_nothing_in_prose(self):
        """Measured: the player held a pistol and nothing else in 100% of 1436
        harvested ticks. With no choice to make, the sentence was pure cost -- and
        the deathmatch prompt sits right on the 512-token formatting limit."""
        from laya_doom.state import narrate, serialize

        obs = observation(label("Blood"), weapon_slot=2, weapon_ammo=50.0, weapons_held=(2,))
        assert "holding" not in narrate(obs)
        # ...but the structured field survives, because a student still needs it.
        assert serialize(obs)["weapon_in_hand"] == "pistol"
        assert "other_weapons_you_are_carrying" not in serialize(obs)

    def test_other_weapons_reach_the_serialized_state(self):
        from laya_doom.state import serialize

        state = serialize(observation(label("Blood"), weapon_slot=4, weapon_ammo=30.0,
                                      weapons_held=(2, 3, 4, 6)))
        assert state["weapon_in_hand"] == "chaingun"
        assert set(state["other_weapons_you_are_carrying"]) == {"pistol", "shotgun", "plasma rifle"}

    def test_maps_without_weapons_are_unaffected(self):
        from laya_doom.state import narrate

        text = narrate(observation(label("Demon")))
        assert "holding" not in text
