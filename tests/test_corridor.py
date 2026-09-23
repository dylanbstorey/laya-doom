"""deadly_corridor: goal-aware state, the corridor action space, and its baselines.

The corridor is a different problem from defend_the_center -- navigation under
fire, with a destination and a heavy death penalty -- so it gets its own action
vocabulary and its own reference policies.
"""

from __future__ import annotations

import json

import pytest

from laya_doom import scenarios
from laya_doom.actions import ANSWER_BUTTONS, from_answers, from_decision
from laya_doom.baselines import AlwaysForwardClient, CorridorScriptedClient, RandomCorridorClient
from laya_doom.questions import CORRIDOR_BATTERY
from laya_doom.state import journey_phrase, narrate, observe, serialize

# The corridor's full button set, in ViZDoom's own order.
CORRIDOR_BUTTONS = ["MOVE_LEFT", "MOVE_RIGHT", "ATTACK", "MOVE_FORWARD",
                    "MOVE_BACKWARD", "TURN_LEFT", "TURN_RIGHT"]


def label(name: str, *, bbox=(150, 100, 20, 40), x=300.0, y=0.0) -> dict:
    return {"name": name, "x": x, "y": y, "bbox": list(bbox)}


def corridor_observation(*labels, health=100.0, position_x=0.0, ammo=26.0):
    return observe(labels, health=health, ammo=ammo, player=(position_x, 0.0),
                   goal_x=1312.0, position_x=position_x)


class TestScenarioConfig:
    def test_corridor_has_a_goal_and_the_centre_does_not(self):
        assert scenarios.DEADLY_CORRIDOR.has_goal
        assert scenarios.DEADLY_CORRIDOR.goal_x == 1312.0
        assert not scenarios.DEFEND_THE_CENTER.has_goal

    def test_each_scenario_brings_its_own_battery(self):
        assert list(scenarios.DEADLY_CORRIDOR.battery) == ["fire", "move"]
        assert list(scenarios.DEFEND_THE_CENTER.battery) == ["fire", "turn"]

    def test_corridor_runs_a_slower_cadence(self):
        """Seven criteria and a longer state cost tokens; buy headroom, don't skip slots."""
        assert scenarios.DEADLY_CORRIDOR.interval_tics > scenarios.DEFEND_THE_CENTER.interval_tics

    def test_unknown_scenario_falls_back_rather_than_raising(self):
        fallback = scenarios.get("my_way_home")
        assert fallback.name == "my_way_home"
        assert not fallback.has_goal


class TestGoalAwareState:
    def test_progress_is_reported_as_a_percentage(self):
        state = serialize(corridor_observation(label("Zombieman"), position_x=656.0))
        assert state["percent_of_the_way_to_the_goal"] == 50

    def test_progress_is_absent_without_a_goal(self):
        state = serialize(observe([label("Demon")], health=100, ammo=26, player=(0.0, 0.0)))
        assert "percent_of_the_way_to_the_goal" not in state

    def test_progress_is_clamped(self):
        assert corridor_observation(position_x=-50.0).progress == 0.0
        assert corridor_observation(position_x=99_999.0).progress == 1.0

    def test_journey_phrase_tightens_as_the_vest_nears(self):
        far = journey_phrase(corridor_observation(position_x=0.0))
        near = journey_phrase(corridor_observation(position_x=1250.0))
        assert "very long way off" in far
        assert "almost there" in near

    def test_an_empty_view_means_the_way_is_clear(self):
        """On a map with somewhere to be, nothing visible is good news -- not a
        reason to stand and search, which is what the centre map's wording says."""
        text = narrate(corridor_observation(position_x=300.0))
        assert "the way ahead is clear" in text
        assert "sweep the room" not in text

    def test_the_journey_is_mentioned_alongside_enemies(self):
        text = narrate(corridor_observation(label("Zombieman"), position_x=400.0))
        assert "vest" in text and "nearest enemy" in text

    def test_corridor_state_stays_within_the_context_budget(self):
        state = serialize(corridor_observation(
            label("Zombieman", x=200.0, bbox=(40, 0, 20, 40)),
            label("ShotgunGuy", x=500.0, bbox=(240, 0, 20, 40)),
            label("ChaingunGuy", x=900.0, bbox=(150, 0, 20, 40)),
            position_x=600.0, health=20.0,
        ))
        assert len(json.dumps(state)) < 1200


class TestCorridorActions:
    @pytest.mark.parametrize("answer,button", [
        ("advance", "MOVE_FORWARD"),
        ("retreat", "MOVE_BACKWARD"),
        ("dodge_left", "MOVE_LEFT"),
        ("dodge_right", "MOVE_RIGHT"),
        ("aim_left", "TURN_LEFT"),
        ("aim_right", "TURN_RIGHT"),
    ])
    def test_each_answer_presses_its_button(self, answer, button):
        action = from_answers(CORRIDOR_BUTTONS, fire=False, turn=answer)
        assert action[CORRIDOR_BUTTONS.index(button)] == 1
        assert sum(action) == 1, "exactly one button, and not the attack"

    def test_hold_presses_nothing(self):
        assert sum(from_answers(CORRIDOR_BUTTONS, fire=False, turn="hold")) == 0

    def test_firing_combines_with_movement(self):
        action = from_answers(CORRIDOR_BUTTONS, fire=True, turn="advance")
        assert action[CORRIDOR_BUTTONS.index("ATTACK")] == 1
        assert action[CORRIDOR_BUTTONS.index("MOVE_FORWARD")] == 1

    def test_every_corridor_answer_is_mapped(self):
        for answer in CORRIDOR_BATTERY["move"]["criteria"]:
            assert answer in ANSWER_BUTTONS, f"{answer} has no button"

    def test_the_move_answer_drives_the_action(self):
        """The corridor names its choice `move`, the centre map names it `turn`;
        both must reach the same mapping."""
        decision = CorridorScriptedClient().decide(
            {"an_enemy_is_lined_up_with_your_crosshair": False, "health": 100,
             "nearest_enemy": {"where": "to the left"}},
            CORRIDOR_BATTERY,
        )
        assert "move" in decision.answers
        action = from_decision(CORRIDOR_BUTTONS, decision)
        assert action[CORRIDOR_BUTTONS.index("TURN_LEFT")] == 1


class TestCorridorBaselines:
    def test_always_forward_walks_and_shoots(self):
        decision = AlwaysForwardClient().decide({}, CORRIDOR_BATTERY)
        assert decision["move"].value == "advance"
        assert decision["fire"].value == 1.0

    def test_scripted_holds_and_fires_when_lined_up(self):
        decision = CorridorScriptedClient().decide(
            {"an_enemy_is_lined_up_with_your_crosshair": True, "health": 100}, CORRIDOR_BATTERY)
        assert decision["move"].value == "hold"
        assert decision["fire"].value == 1.0

    def test_scripted_advances_when_the_way_is_clear(self):
        decision = CorridorScriptedClient().decide(
            {"an_enemy_is_lined_up_with_your_crosshair": False, "health": 100}, CORRIDOR_BATTERY)
        assert decision["move"].value == "advance"

    def test_scripted_retreats_when_nearly_dead(self):
        decision = CorridorScriptedClient().decide(
            {"an_enemy_is_lined_up_with_your_crosshair": False, "health": 10,
             "nearest_enemy": {"where": "to the left"}},
            CORRIDOR_BATTERY,
        )
        assert decision["move"].value == "retreat"

    def test_random_covers_the_whole_corridor_action_space(self):
        from laya_doom.baselines import CORRIDOR_OPTIONS

        client = RandomCorridorClient(seed=3)
        seen = {str(client.decide({}, CORRIDOR_BATTERY)["move"].value) for _ in range(400)}
        assert seen == set(CORRIDOR_OPTIONS)
