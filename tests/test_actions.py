from __future__ import annotations

import pytest

from laya_doom.actions import from_answers, from_decision, neutral
from laya_doom.client import Answer, Decision

BUTTONS = ["TURN_LEFT", "TURN_RIGHT", "ATTACK"]


def decision(fire: float, turn: str) -> Decision:
    return Decision(
        answers={
            "fire": Answer("fire", "noul", fire, {"true": fire, "false": 1 - fire}, 0.5),
            "turn": Answer("turn", "choice", turn, {turn: 0.8}, 0.4),
        },
        latency_ms=62.0,
    )


class TestButtonMapping:
    def test_neutral_presses_nothing(self):
        assert neutral(BUTTONS) == [0, 0, 0]

    def test_fire_presses_attack_only(self):
        assert from_answers(BUTTONS, fire=True, turn="hold") == [0, 0, 1]

    def test_turn_left(self):
        assert from_answers(BUTTONS, fire=False, turn="left") == [1, 0, 0]

    def test_turn_right(self):
        assert from_answers(BUTTONS, fire=False, turn="right") == [0, 1, 0]

    def test_fire_and_turn_together(self):
        assert from_answers(BUTTONS, fire=True, turn="right") == [0, 1, 1]

    def test_hold_does_not_turn(self):
        assert from_answers(BUTTONS, fire=False, turn="hold") == [0, 0, 0]

    def test_unknown_turn_value_presses_nothing(self):
        assert from_answers(BUTTONS, fire=False, turn="sideways") == [0, 0, 0]

    def test_missing_buttons_are_skipped(self):
        """deadly_corridor exposes movement buttons and no TURN_LEFT in some configs."""
        assert from_answers(["ATTACK", "MOVE_FORWARD"], fire=True, turn="left") == [1, 0]


class TestThreshold:
    def test_above_threshold_fires(self):
        assert from_decision(BUTTONS, decision(0.72, "hold")) == [0, 0, 1]

    def test_below_threshold_holds_fire(self):
        assert from_decision(BUTTONS, decision(0.31, "hold")) == [0, 0, 0]

    def test_exactly_at_threshold_fires(self):
        assert from_decision(BUTTONS, decision(0.5, "hold")) == [0, 0, 1]

    def test_threshold_is_configurable(self):
        # A cautious trigger: only fire when very confident.
        assert from_decision(BUTTONS, decision(0.72, "hold"), fire_threshold=0.9) == [0, 0, 0]

    def test_turn_comes_through_with_fire(self):
        assert from_decision(BUTTONS, decision(0.99, "left")) == [1, 0, 1]

    def test_absent_answers_are_neutral(self):
        assert from_decision(BUTTONS, Decision(answers={}, latency_ms=1.0)) == [0, 0, 0]


class TestScan:
    """`scan` is the model choosing to search. The code only renders it."""

    def test_scan_turns(self):
        assert from_answers(BUTTONS, fire=False, turn="scan") == [0, 1, 0]

    def test_scan_uses_one_consistent_direction(self):
        """A fixed direction sweeps the whole room; alternating would stall the
        view inside one arc and defeat the point of searching."""
        repeated = [from_answers(BUTTONS, fire=False, turn="scan") for _ in range(5)]
        assert all(action == repeated[0] for action in repeated)

    def test_scan_still_allows_firing(self):
        assert from_answers(BUTTONS, fire=True, turn="scan") == [0, 1, 1]

    def test_hold_and_scan_differ(self):
        assert from_answers(BUTTONS, turn="hold") != from_answers(BUTTONS, turn="scan")


class TestBaselineParity:
    """The baselines must have the same action space as the model, or the
    comparison flatters whichever one can do more."""

    def test_scripted_scans_when_nothing_is_visible(self):
        from laya_doom.baselines import ScriptedClient

        decision = ScriptedClient().decide(
            {"enemies_in_sight": 0, "an_enemy_is_lined_up_with_your_crosshair": False},
            {},
        )
        assert decision["turn"].value == "scan"

    def test_scripted_aims_when_an_enemy_is_off_centre(self):
        from laya_doom.baselines import ScriptedClient

        decision = ScriptedClient().decide(
            {
                "an_enemy_is_lined_up_with_your_crosshair": False,
                "nearest_enemy": {"where": "far to the left", "lined_up_with_crosshair": False},
            },
            {},
        )
        assert decision["turn"].value == "left"
        assert decision["fire"].value == 0.0

    def test_scripted_holds_and_fires_when_lined_up(self):
        from laya_doom.baselines import ScriptedClient

        decision = ScriptedClient().decide(
            {
                "an_enemy_is_lined_up_with_your_crosshair": True,
                "nearest_enemy": {"where": "centred in your crosshair", "lined_up_with_crosshair": True},
            },
            {},
        )
        assert decision["turn"].value == "hold"
        assert decision["fire"].value == 1.0

    def test_random_can_choose_every_option(self):
        from laya_doom.baselines import RandomClient

        client = RandomClient(seed=1)
        seen = {str(client.decide({}, {})["turn"].value) for _ in range(200)}
        assert seen == {"left", "right", "hold", "scan"}
