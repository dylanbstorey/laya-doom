"""Serializer tests.

Concentrated on the things that fail *silently*: a flipped bearing sign aims the
wrong way, and a mis-classified label has the model shooting at blood splatter.
Neither is visible from watching gameplay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from laya_doom.state import (
    Observation,
    from_fixture,
    is_monster,
    narrate,
    observe,
    plain_name,
    serialize,
)

FIXTURES = Path(__file__).parent.parent / "bench" / "fixtures"


def label(name: str, *, bbox=(150, 100, 20, 40), x=300.0, y=0.0) -> dict:
    return {"name": name, "x": x, "y": y, "bbox": list(bbox)}


def observation(*labels, health=100.0, ammo=26.0, width=320) -> Observation:
    return observe(labels, health=health, ammo=ammo, screen_width=width, player=(0.0, 0.0))


class TestLabelClassification:
    """The label buffer reports far more than enemies."""

    @pytest.mark.parametrize("name", ["Demon", "Zombieman", "ShotgunGuy", "ChaingunGuy", "DoomImp", "Cacodemon"])
    def test_monsters_are_enemies(self, name):
        assert is_monster(name)

    @pytest.mark.parametrize("name", ["MarineChainsawVzd", "MarineBFG", "MarineRocket"])
    def test_vizdoom_custom_marines_are_enemies(self, name):
        assert is_monster(name)

    @pytest.mark.parametrize("name", ["Blood", "BulletPuff", "TeleportFog", "Medikit", "Clip",
                                      "GreenArmor", "ArmorBonus", "Shotgun", "DoomPlayer", "DoomImpBall"])
    def test_effects_items_and_self_are_not_enemies(self, name):
        """All of these appear in captured fixtures. Blood and BulletPuff are
        produced *by shooting*, so counting them would create a feedback loop."""
        assert not is_monster(name)

    @pytest.mark.parametrize("name", ["DeadZombieman", "DeadShotgunGuy", "DeadMarine"])
    def test_corpses_are_not_enemies(self, name):
        assert not is_monster(name)

    def test_engine_names_become_plain_words(self):
        assert plain_name("MarineChainsawVzd") == "a marine"
        assert plain_name("DoomImp") == "an imp"
        assert plain_name("Demon") == "a demon"

    def test_unknown_monster_still_gets_a_word(self):
        assert plain_name("SomeNewMonster") == "an enemy"


class TestBearing:
    """Sign errors here invert aim and are invisible from gameplay."""

    def test_enemy_left_of_centre_reads_left(self):
        obs = observation(label("Demon", bbox=(60, 100, 20, 40)))
        enemy = obs.nearest
        assert enemy.offset < 0
        assert enemy.side == "left"
        assert "left" in enemy.bearing_phrase
        assert "right" not in enemy.bearing_phrase

    def test_enemy_right_of_centre_reads_right(self):
        obs = observation(label("Demon", bbox=(240, 100, 20, 40)))
        enemy = obs.nearest
        assert enemy.offset > 0
        assert enemy.side == "right"
        assert "right" in enemy.bearing_phrase

    def test_crosshair_inside_bounding_box_is_lined_up(self):
        # Screen centre is 160; this box spans 150..170.
        obs = observation(label("Demon", bbox=(150, 100, 20, 40)))
        assert obs.nearest.in_crosshair
        assert obs.nearest.bearing_phrase == "centred in your crosshair"

    def test_crosshair_outside_bounding_box_is_not_lined_up(self):
        obs = observation(label("Demon", bbox=(200, 100, 20, 40)))
        assert not obs.nearest.in_crosshair

    def test_bearing_widens_with_offset(self):
        near = observation(label("Demon", bbox=(180, 100, 10, 40))).nearest
        far = observation(label("Demon", bbox=(300, 100, 10, 40))).nearest
        assert near.bearing_phrase == "slightly right"
        assert far.bearing_phrase == "far to the right"

    def test_offset_scales_with_screen_width(self):
        """A 640-wide screen must not read as twice as far off-centre."""
        narrow = observe([label("Demon", bbox=(240, 0, 20, 40))], health=100, ammo=1,
                         screen_width=320, player=(0.0, 0.0)).nearest
        wide = observe([label("Demon", bbox=(480, 0, 40, 80))], health=100, ammo=1,
                       screen_width=640, player=(0.0, 0.0)).nearest
        assert narrow.offset_fraction == pytest.approx(wide.offset_fraction)
        assert narrow.bearing_phrase == wide.bearing_phrase


class TestDistanceAndOrdering:
    def test_nearest_enemy_comes_first(self):
        obs = observation(
            label("Demon", x=700.0, bbox=(60, 100, 20, 40)),
            label("Zombieman", x=120.0, bbox=(240, 100, 20, 40)),
        )
        assert obs.nearest.name == "Zombieman"
        assert obs.nearest.distance == pytest.approx(120.0)

    def test_distance_phrases_follow_calibrated_bands(self):
        assert observation(label("Demon", x=80.0)).nearest.distance_phrase == "right on top of you"
        assert observation(label("Demon", x=300.0)).nearest.distance_phrase == "close"
        assert observation(label("Demon", x=500.0)).nearest.distance_phrase == "a moderate distance away"
        assert observation(label("Demon", x=900.0)).nearest.distance_phrase == "far away"

    def test_enemy_list_is_capped(self):
        labels = [label("Demon", x=float(100 * i), bbox=(10 * i, 0, 5, 5)) for i in range(1, 9)]
        obs = observe(labels, health=100, ammo=1, player=(0.0, 0.0), max_enemies=3)
        assert len(obs.enemies) == 3


class TestNarration:
    def test_no_enemies_is_stated_plainly(self):
        text = narrate(observation(label("Blood"), label("BulletPuff")))
        assert "No enemy is in sight" in text

    def test_lined_up_is_stated_explicitly(self):
        text = narrate(observation(label("Demon", bbox=(150, 100, 20, 40), x=200.0)))
        assert "shooting now would hit it" in text

    def test_low_health_is_mentioned(self):
        assert "badly hurt" in narrate(observation(label("Demon"), health=15.0))
        assert "badly hurt" not in narrate(observation(label("Demon"), health=90.0))

    def test_no_ammo_is_mentioned(self):
        assert "out of ammunition" in narrate(observation(label("Demon"), ammo=0.0))

    def test_extra_enemies_are_counted(self):
        text = narrate(observation(
            label("Demon", x=100.0, bbox=(150, 0, 20, 40)),
            label("Zombieman", x=400.0, bbox=(40, 0, 20, 40)),
        ))
        assert "1 more enemy in sight" in text


class TestSerializedShape:
    def test_keys_the_questions_rely_on(self):
        state = serialize(observation(label("Demon", bbox=(150, 100, 20, 40))))
        assert set(state) >= {"observation", "health", "ammunition", "enemies_in_sight", "nearest_enemy"}
        assert state["nearest_enemy"]["lined_up_with_crosshair"] is True

    def test_nearest_enemy_absent_when_none_visible(self):
        state = serialize(observation(label("Blood")))
        assert "nearest_enemy" not in state
        assert state["enemies_in_sight"] == 0

    def test_state_is_json_serialisable(self):
        json.dumps(serialize(observation(label("Demon"))))


class TestAgainstRecordedFixtures:
    """Every captured tick must serialize without raising and stay in budget."""

    @pytest.mark.parametrize("scenario", ["defend_the_center", "deadly_corridor", "defend_the_line", "deathmatch"])
    def test_fixtures_serialize_within_context_budget(self, scenario):
        path = FIXTURES / f"{scenario}.json"
        if not path.exists():
            pytest.skip(f"no fixtures captured for {scenario}")
        for fixture in json.loads(path.read_text()):
            state = serialize(from_fixture(fixture))
            rendered = json.dumps(state)
            # The typed-decisions context is 1024 tokens; ~4 chars/token leaves
            # ample headroom for the question text alongside.
            assert len(rendered) < 1200, f"{scenario} tick {fixture['tick']} serialized to {len(rendered)} chars"

    def test_no_effect_labels_leak_into_enemies(self):
        path = FIXTURES / "deathmatch.json"
        if not path.exists():
            pytest.skip("no deathmatch fixtures")
        for fixture in json.loads(path.read_text()):
            for enemy in from_fixture(fixture).enemies:
                assert is_monster(enemy.name)
                assert not enemy.name.startswith(("Blood", "BulletPuff", "Dead"))


class TestCrosshairTargetVersusNearest:
    """A real fixture has the closest demon far left while a marine further away
    sits dead centre. Firing depends on the centred one, aiming on the closest."""

    def setup_method(self):
        self.obs = observation(
            label("Demon", x=100.0, bbox=(20, 0, 20, 40)),      # closest, far left
            label("MarineChainsawVzd", x=500.0, bbox=(150, 0, 20, 40)),  # further, centred
        )

    def test_nearest_is_the_closest_enemy(self):
        assert self.obs.nearest.name == "Demon"
        assert not self.obs.nearest.in_crosshair

    def test_crosshair_target_is_the_centred_enemy(self):
        assert self.obs.crosshair_target.name == "MarineChainsawVzd"

    def test_narration_does_not_contradict_itself(self):
        text = narrate(self.obs)
        assert "further away is centred in your crosshair" in text
        assert "shooting now would hit that one" in text

    def test_serialized_state_flags_the_shot(self):
        state = serialize(self.obs)
        assert state["an_enemy_is_lined_up_with_your_crosshair"] is True
        # ...while the nearest enemy is still reported as not lined up.
        assert state["nearest_enemy"]["lined_up_with_crosshair"] is False

    def test_no_target_when_nothing_is_centred(self):
        obs = observation(label("Demon", x=100.0, bbox=(20, 0, 20, 40)))
        assert obs.crosshair_target is None
        assert serialize(obs)["an_enemy_is_lined_up_with_your_crosshair"] is False
        assert "No enemy is lined up" in narrate(obs)
