"""Loop timing tests.

The latch and the generation guard are the two pieces that keep a slow or stale
reply from corrupting play, and neither is observable from watching Doom. Both
are exercised here against a manual clock and a fake game, so no model and no
Doom process are involved.
"""

from __future__ import annotations

import pytest

from concurrent.futures import Future

from laya_doom.client import Answer, Decision, DecisionError, StubClient
from laya_doom.loop import ActionLatch, DecisionLoop, EpisodeResult, ManualClock, TickRecord
from laya_doom.questions import BATTERY

BUTTONS = ["TURN_LEFT", "TURN_RIGHT", "ATTACK"]


def decision(fire: float = 0.9, turn: str = "right") -> Decision:
    return Decision(
        answers={
            "fire": Answer("fire", "noul", fire, {"true": fire, "false": 1 - fire}, 0.6),
            "turn": Answer("turn", "choice", turn, {turn: 0.8}, 0.3),
        },
        latency_ms=62.0,
    )


class TestActionLatch:
    def test_starts_neutral(self):
        latch = ActionLatch(BUTTONS)
        assert latch.current(0.0) == [0, 0, 0]

    def test_applied_reply_is_held_for_one_interval(self):
        latch = ActionLatch(BUTTONS, interval_ms=100)
        latch.apply(decision(turn="right"), latch.generation, 0.0, fire_threshold=0.5)
        assert latch.current(0.0) == [0, 1, 1]
        assert latch.current(99.0) == [0, 1, 1]

    def test_action_decays_to_neutral_after_the_interval(self):
        """Without this a slow backend leaves a key held down indefinitely."""
        latch = ActionLatch(BUTTONS, interval_ms=100)
        latch.apply(decision(), latch.generation, 0.0, fire_threshold=0.5)
        assert latch.current(100.0) == [0, 0, 0]
        assert latch.current(5000.0) == [0, 0, 0]

    def test_a_later_reply_extends_the_hold(self):
        latch = ActionLatch(BUTTONS, interval_ms=100)
        latch.apply(decision(turn="right"), latch.generation, 0.0, fire_threshold=0.5)
        latch.apply(decision(turn="left"), latch.generation, 80.0, fire_threshold=0.5)
        assert latch.current(150.0) == [1, 0, 1]
        assert latch.current(180.0) == [0, 0, 0]

    def test_reply_from_a_superseded_generation_is_dropped(self):
        latch = ActionLatch(BUTTONS, interval_ms=100)
        inflight = latch.generation
        latch.bump_generation()  # episode restarted while the request was out
        assert latch.apply(decision(), inflight, 0.0, fire_threshold=0.5) is False
        assert latch.current(0.0) == [0, 0, 0]
        assert latch.stale_replies == 1

    def test_bumping_generation_clears_a_held_action(self):
        latch = ActionLatch(BUTTONS, interval_ms=100)
        latch.apply(decision(), latch.generation, 0.0, fire_threshold=0.5)
        latch.bump_generation()
        assert latch.current(10.0) == [0, 0, 0]

    def test_fire_threshold_is_honoured(self):
        latch = ActionLatch(BUTTONS, interval_ms=100)
        latch.apply(decision(fire=0.6, turn="hold"), latch.generation, 0.0, fire_threshold=0.9)
        assert latch.current(0.0) == [0, 0, 0]


class FakeGame:
    """Minimal stand-in for a ViZDoom game."""

    def __init__(self, *, ticks_until_done: int = 20, enemy_bbox=(200, 100, 20, 40)) -> None:
        self.ticks_until_done = ticks_until_done
        self.enemy_bbox = enemy_bbox
        self.advanced: list[int] = []
        self.actions: list[list[int]] = []
        self.episodes = 0
        self._tics = 0

    # -- the parts the loop touches
    def new_episode(self):
        self.episodes += 1
        self._tics = 0

    def is_episode_finished(self):
        return self._tics >= self.ticks_until_done

    def set_action(self, action):
        self.actions.append(list(action))

    def advance_action(self, tics, _update_state=True):
        self.advanced.append(tics)
        self._tics += tics

    def get_available_buttons(self):
        return ["Button.TURN_LEFT", "Button.TURN_RIGHT", "Button.ATTACK"]

    def get_available_game_variables(self):
        return ["GameVariable.HEALTH", "GameVariable.AMMO2", "GameVariable.KILLCOUNT"]

    def get_screen_width(self):
        return 320

    def get_total_reward(self):
        return 7.0

    def get_state(self):
        if self.is_episode_finished():
            return None
        return FakeState(self.enemy_bbox)


class FakeLabel:
    def __init__(self, name, x, y, bbox):
        self.object_name = name
        self.object_position_x, self.object_position_y = x, y
        self.x, self.y, self.width, self.height = bbox


class FakeState:
    def __init__(self, enemy_bbox):
        self.game_variables = [100.0, 26.0, 3.0]
        self.labels = [
            FakeLabel("DoomPlayer", 0.0, 0.0, (135, 155, 54, 84)),
            FakeLabel("Demon", 300.0, 0.0, enemy_bbox),
        ]
        self.screen_buffer = "frame"


def build_loop(client, *, interval_ms=100.0, ticks_until_done=20):
    game = FakeGame(ticks_until_done=ticks_until_done)
    loop = DecisionLoop(
        game, client, BATTERY,
        interval_ms=interval_ms, clock=ManualClock(), real_time=False, use_thread=False,
    )
    return game, loop


class TestEpisode:
    def test_a_full_episode_runs_with_no_model(self):
        client = StubClient({"fire": 0.9, "turn": "right"})
        game, loop = build_loop(client)
        records: list[TickRecord] = []
        result = loop.run_episode(on_tick=records.append)
        loop.close()

        assert game.episodes == 1
        assert result.ticks > 0
        assert result.decisions > 0
        assert result.errors == 0
        assert result.score == 7.0
        assert len(records) == result.ticks

    def test_the_action_actually_reaches_the_game(self):
        """advance_action takes no buttons. Without set_action the world advances
        with nothing pressed and the policy silently never acts -- which looks
        exactly like a policy that cannot play."""
        client = StubClient({"fire": 0.9, "turn": "right"})
        game, loop = build_loop(client)
        loop.run_episode()
        loop.close()

        assert game.actions, "no action was ever handed to the game"
        assert len(game.actions) == len(game.advanced)
        assert any(any(button) for button in game.actions), "every action was neutral"
        assert [0, 1, 1] in game.actions, "fire+turn-right never reached the game"

    def test_every_record_carries_the_state_the_model_saw(self):
        client = StubClient({"fire": 0.9, "turn": "right"})
        _game, loop = build_loop(client)
        records: list[TickRecord] = []
        loop.run_episode(on_tick=records.append)
        loop.close()
        assert all("observation" in record.state for record in records)
        assert all(record.buttons == BUTTONS for record in records)

    def test_max_ticks_stops_the_episode(self):
        client = StubClient({"fire": 0.0, "turn": "hold"})
        _game, loop = build_loop(client, ticks_until_done=10_000)
        result = loop.run_episode(max_ticks=5)
        loop.close()
        assert result.ticks == 5

    def test_should_stop_is_honoured(self):
        client = StubClient({"fire": 0.0, "turn": "hold"})
        _game, loop = build_loop(client, ticks_until_done=10_000)
        calls = {"n": 0}

        def should_stop():
            calls["n"] += 1
            return calls["n"] > 3

        result = loop.run_episode(should_stop=should_stop)
        loop.close()
        assert result.ticks == 3

    def test_a_slow_backend_still_finishes_the_episode(self):
        """A 250 ms reply against a 100 ms interval must not stall anything."""
        client = StubClient({"fire": 0.9, "turn": "left"}, delay_ms=250)
        game = FakeGame(ticks_until_done=40)
        loop = DecisionLoop(game, client, BATTERY, interval_ms=100.0, real_time=False)
        result = loop.run_episode()
        loop.close()

        assert result.ticks > 0
        assert result.errors == 0

    def test_a_slot_opening_while_a_request_is_out_is_skipped_not_queued(self):
        """The skip guard, tested directly: queueing would let the loop fall
        arbitrarily far behind, and the server refuses concurrent requests anyway."""
        client = StubClient({"fire": 0.9, "turn": "left"})
        _game, loop = build_loop(client)
        result = EpisodeResult(ticks=0, game_tics=0, score=0.0, killcount=0.0,
                               decisions=0, applied=0, skipped_slots=0, stale_replies=0, errors=0)
        state = {"observation": "x"}

        interval = loop.interval_ms  # 4 tics, ~114.3 ms

        # Slot open, nothing in flight: dispatch.
        next_slot = loop._service_slot(0.0, 0.0, state, result)
        assert result.decisions == 1
        assert next_slot == pytest.approx(interval)

        # Pretend that request is still out when the next slot falls due.
        loop._inflight = Future()
        next_slot = loop._service_slot(interval, next_slot, state, result)
        loop.close()

        assert result.decisions == 1, "must not dispatch a second concurrent request"
        assert result.skipped_slots == 1
        assert next_slot == pytest.approx(2 * interval), "the schedule advances rather than drifting"

    def test_a_long_stall_skips_whole_slots_rather_than_drifting(self):
        client = StubClient({"fire": 0.9, "turn": "left"})
        _game, loop = build_loop(client)
        result = EpisodeResult(ticks=0, game_tics=0, score=0.0, killcount=0.0,
                               decisions=0, applied=0, skipped_slots=0, stale_replies=0, errors=0)
        # Three intervals late: the schedule jumps past the missed slots.
        interval = loop.interval_ms
        next_slot = loop._service_slot(3.05 * interval, 0.0, {"observation": "x"}, result)
        loop.close()
        assert next_slot == pytest.approx(4 * interval)

    def test_backend_errors_mid_episode_are_counted_not_raised(self):
        class DiesAfterWarmup:
            """Answers during warmup, then fails -- a server dying mid-episode."""

            def __init__(self):
                self.calls = 0

            def decide(self, state, questions):
                self.calls += 1
                if self.calls <= 2:  # WARMUP_CALLS
                    return StubClient({"fire": 0.1, "turn": "hold"}).decide(state, questions)
                raise RuntimeError("backend exploded")

            def close(self):
                pass

        _game, loop = build_loop(DiesAfterWarmup(), ticks_until_done=30)
        result = loop.run_episode()
        loop.close()
        assert result.errors > 0
        assert result.ticks > 0, "the episode must survive a backend failure"

    def test_a_backend_broken_from_the_start_fails_fast_at_warmup(self):
        """Better than running a whole episode that makes no decisions."""
        class BrokenClient:
            def decide(self, state, questions):
                raise RuntimeError("backend exploded")

            def close(self):
                pass

        _game, loop = build_loop(BrokenClient(), ticks_until_done=30)
        with pytest.raises(DecisionError, match="warmup failed"):
            loop.run_episode()
        loop.close()


class TestEpisodeResult:
    def test_latency_percentiles(self):
        client = StubClient({"fire": 0.9, "turn": "right"})
        _game, loop = build_loop(client)
        result = loop.run_episode()
        loop.close()
        if result.latencies_ms:
            assert result.latency_p50 is not None
            assert result.latency_p95 >= result.latency_p50

    def test_summary_mentions_the_honest_numbers(self):
        client = StubClient({"fire": 0.9, "turn": "right"})
        _game, loop = build_loop(client)
        summary = loop.run_episode().summary()
        loop.close()
        for field in ["score=", "decisions=", "skipped=", "stale=", "errors=", "latency p50="]:
            assert field in summary


def scan_decision(fire: float = 0.1) -> Decision:
    return Decision(
        answers={
            "fire": Answer("fire", "noul", fire, {"true": fire, "false": 1 - fire}, 0.6),
            "turn": Answer("turn", "choice", "scan", {"scan": 0.7}, 0.3),
        },
        latency_ms=62.0,
    )


class TestSweepCommitment:
    """One decision interval turns only ~10.6 degrees at Doom's measured 2.64
    deg/tic, and the model re-decides every interval, so an uncommitted `scan`
    oscillates inside a narrow arc instead of searching the room."""

    def test_a_sweep_covers_at_least_thirty_degrees(self):
        from laya_doom.loop import SWEEP_TICS, TURN_DEGREES_PER_TIC

        assert SWEEP_TICS * TURN_DEGREES_PER_TIC >= 30.0

    def test_scan_survives_the_ordinary_interval_decay(self):
        latch = ActionLatch(BUTTONS, interval_ms=100, sweep_ms=343)
        latch.apply(scan_decision(), latch.generation, 0.0, fire_threshold=0.5)
        turning = [0, 1, 0]
        assert latch.current(0.0) == turning
        # Past one interval, where a normal action would have decayed to neutral.
        assert latch.current(150.0) == turning
        assert latch.current(300.0) == turning

    def test_the_sweep_ends_when_its_arc_is_done(self):
        latch = ActionLatch(BUTTONS, interval_ms=100, sweep_ms=343)
        latch.apply(scan_decision(), latch.generation, 0.0, fire_threshold=0.5)
        assert latch.current(400.0) == [0, 0, 0]
        assert latch.sweeping is False

    def test_the_sweep_never_reverses_mid_arc(self):
        """One sweep is one direction."""
        latch = ActionLatch(BUTTONS, interval_ms=100, sweep_ms=343)
        latch.apply(scan_decision(), latch.generation, 0.0, fire_threshold=0.5)
        first = latch.current(0.0)
        # More `scan` answers arrive mid-sweep; they continue it, not restart it.
        latch.apply(scan_decision(), latch.generation, 120.0, fire_threshold=0.5)
        latch.apply(scan_decision(), latch.generation, 240.0, fire_threshold=0.5)
        assert latch.current(250.0) == first
        assert latch.sweeps_started == 1, "a continuing sweep must not count as a new one"
        assert latch.current(400.0) == [0, 0, 0], "and must not be extended indefinitely"

    def test_spotting_an_enemy_interrupts_the_sweep(self):
        """Finishing the arc first would cost the shot."""
        latch = ActionLatch(BUTTONS, interval_ms=100, sweep_ms=343)
        latch.apply(scan_decision(), latch.generation, 0.0, fire_threshold=0.5)
        assert latch.sweeping

        latch.apply(decision(fire=0.9, turn="left"), latch.generation, 100.0, fire_threshold=0.5)
        assert latch.sweeping is False
        assert latch.sweeps_interrupted == 1
        assert latch.current(100.0) == [1, 0, 1], "the aim answer must take over at once"

    def test_restarting_an_episode_clears_a_sweep(self):
        latch = ActionLatch(BUTTONS, interval_ms=100, sweep_ms=343)
        latch.apply(scan_decision(), latch.generation, 0.0, fire_threshold=0.5)
        latch.bump_generation()
        assert latch.sweeping is False
        assert latch.current(10.0) == [0, 0, 0]

    def test_sweeps_are_reported_on_the_episode(self):
        client = StubClient({"fire": 0.1, "turn": "scan"})
        _game, loop = build_loop(client, ticks_until_done=60)
        result = loop.run_episode()
        loop.close()
        assert result.sweeps > 0
        assert "sweeps=" in result.summary()
