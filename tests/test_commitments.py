"""Bounded commitments -- the only thing that has ever fixed thrashing here.

Measured three times, and rewording fixed none of them:
  * `scan` reversing every interval, covering 10.6 degrees instead of searching.
  * `aim_left`/`aim_right` oscillating 45%/45% while the player travelled 0%.
  * weapon switches on 98% of deathmatch decisions.
"""

from __future__ import annotations

import pytest

from laya_doom.client import Answer, Decision
from laya_doom.loop import COMMITMENT_TICS, MS_PER_TIC, URGENCY, ActionLatch

BUTTONS = ["TURN_LEFT", "TURN_RIGHT", "ATTACK", "MOVE_FORWARD", "MOVE_BACKWARD",
           "MOVE_LEFT", "MOVE_RIGHT", "SELECT_WEAPON3", "SELECT_WEAPON4"]


def decide(move: str, *, fire: float = 0.0, weapon: str | None = None) -> Decision:
    answers = {
        "fire": Answer("fire", "noul", fire, {"true": fire, "false": 1 - fire}, 0.5),
        "move": Answer("move", "choice", move, {move: 1.0}, 0.5),
    }
    if weapon is not None:
        answers["weapon"] = Answer("weapon", "choice", weapon, {weapon: 1.0}, 0.5)
    return Decision(answers=answers, latency_ms=60.0)


def latch() -> ActionLatch:
    return ActionLatch(BUTTONS, interval_ms=4 * MS_PER_TIC)


def pressed(action: list[int]) -> set[str]:
    return {name for name, on in zip(BUTTONS, action) if on}


class TestAimThrashing:
    def test_an_equally_urgent_reversal_is_ignored(self):
        """aim_left then aim_right is the 45/45 oscillation, verbatim."""
        it = latch()
        it.apply(decide("aim_left"), it.generation, 0.0, fire_threshold=0.5)
        assert pressed(it.current(0.0)) == {"TURN_LEFT"}

        it.apply(decide("aim_right"), it.generation, 30.0, fire_threshold=0.5)
        assert pressed(it.current(30.0)) == {"TURN_LEFT"}, "must not reverse mid-commitment"
        assert it.moves_ignored == 1

    def test_the_reversal_is_accepted_once_the_commitment_expires(self):
        it = latch()
        it.apply(decide("aim_left"), it.generation, 0.0, fire_threshold=0.5)
        after = COMMITMENT_TICS["aim_left"] * MS_PER_TIC + 1
        it.apply(decide("aim_right"), it.generation, after, fire_threshold=0.5)
        assert pressed(it.current(after)) == {"TURN_RIGHT"}

    def test_a_lined_up_shot_interrupts_aiming_at_once(self):
        """Urgency exists so anti-thrash never costs a shot."""
        it = latch()
        it.apply(decide("aim_left"), it.generation, 0.0, fire_threshold=0.5)
        it.apply(decide("hold", fire=0.9), it.generation, 30.0, fire_threshold=0.5)
        assert pressed(it.current(30.0)) == {"ATTACK"}
        assert it.commitments_interrupted == 1

    def test_trouble_interrupts_aiming(self):
        it = latch()
        it.apply(decide("aim_left"), it.generation, 0.0, fire_threshold=0.5)
        it.apply(decide("retreat"), it.generation, 30.0, fire_threshold=0.5)
        assert pressed(it.current(30.0)) == {"MOVE_BACKWARD"}

    def test_aiming_does_not_interrupt_a_dodge(self):
        it = latch()
        it.apply(decide("dodge_left"), it.generation, 0.0, fire_threshold=0.5)
        it.apply(decide("aim_right"), it.generation, 30.0, fire_threshold=0.5)
        assert pressed(it.current(30.0)) == {"MOVE_LEFT"}

    def test_urgency_ordering_is_what_the_comment_claims(self):
        assert URGENCY["hold"] > URGENCY["retreat"] > URGENCY["aim_left"] >= URGENCY["advance"]


class TestFireIsNeverSuppressed:
    def test_a_fresh_trigger_lands_during_a_committed_turn(self):
        """Holding a turn is execution; refusing a shot would be overriding the
        decision that matters most."""
        it = latch()
        it.apply(decide("scan"), it.generation, 0.0, fire_threshold=0.5)
        assert pressed(it.current(0.0)) == {"TURN_RIGHT"}

        it.apply(decide("scan", fire=0.95), it.generation, 30.0, fire_threshold=0.5)
        assert pressed(it.current(30.0)) == {"TURN_RIGHT", "ATTACK"}

    def test_a_stale_trigger_decays_even_mid_commitment(self):
        it = latch()
        it.apply(decide("scan", fire=0.95), it.generation, 0.0, fire_threshold=0.5)
        mid = 5 * MS_PER_TIC  # past the interval, inside the 12-tic sweep
        assert pressed(it.current(mid)) == {"TURN_RIGHT"}, "the turn holds, the shot does not"


class TestWeaponThrashing:
    def test_a_switch_is_held_before_reconsidering(self):
        it = latch()
        it.apply(decide("advance", weapon="shotgun"), it.generation, 0.0, fire_threshold=0.5)
        assert "SELECT_WEAPON3" in pressed(it.current(0.0))

        it.apply(decide("advance", weapon="chaingun"), it.generation, 30.0, fire_threshold=0.5)
        assert "SELECT_WEAPON4" not in pressed(it.current(30.0))
        assert it.switches_ignored == 1

    def test_switching_is_allowed_again_later(self):
        from laya_doom.loop import WEAPON_COMMITMENT_TICS

        it = latch()
        it.apply(decide("advance", weapon="shotgun"), it.generation, 0.0, fire_threshold=0.5)
        after = WEAPON_COMMITMENT_TICS * MS_PER_TIC + 1
        it.apply(decide("advance", weapon="chaingun"), it.generation, after, fire_threshold=0.5)
        assert "SELECT_WEAPON4" in pressed(it.current(after))

    def test_keep_presses_nothing_and_costs_nothing(self):
        it = latch()
        it.apply(decide("advance", weapon="keep"), it.generation, 0.0, fire_threshold=0.5)
        assert not {"SELECT_WEAPON3", "SELECT_WEAPON4"} & pressed(it.current(0.0))
        assert it.switches_ignored == 0


class TestUncommittedActionsStillDecay:
    def test_advance_decays_after_one_interval(self):
        it = latch()
        it.apply(decide("advance"), it.generation, 0.0, fire_threshold=0.5)
        assert pressed(it.current(0.0)) == {"MOVE_FORWARD"}
        assert pressed(it.current(4 * MS_PER_TIC + 1)) == set()

    def test_a_restart_clears_every_commitment(self):
        it = latch()
        it.apply(decide("scan"), it.generation, 0.0, fire_threshold=0.5)
        it.bump_generation()
        assert pressed(it.current(10.0)) == set()
        assert it.committed is False
