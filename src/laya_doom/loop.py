"""The real-time loop: Doom runs, LAYA decides, neither waits for the other.

Structure is ported from the reference pong demo's ``decisions.mjs`` -- interval,
in-flight guard, generation counter, action latch -- because it is a proven
solution to exactly this problem.

The key choice: the model is called on a **worker thread** while the game keeps
advancing on the main thread at Doom's real tic rate. ViZDoom only moves when
``advance_action`` is called, so it would have been easier to block on each
decision and step the game afterwards. That would also have been dishonest: with
the game frozen while the model thinks, latency costs nothing and the demo proves
nothing about real-time control. Here the world moves on regardless, so a slow
reply is paid for in Doom time, which is the whole point.

Consequences, all of them deliberate:

* A reply applies for exactly one interval, then the action decays to neutral.
  Sluggishness is the visible failure mode, never a desynchronised game clock.
* At most one request is outstanding; the server accepts only one anyway
  (``max_active_requests: 1``). A slot that opens while a request is pending is
  skipped rather than queued, so the loop can never fall behind by accumulating
  work.
* Replies are tagged with a generation. Restarting an episode bumps it, and a
  reply arriving from the previous generation is dropped instead of steering the
  new episode.

Everything is scheduled on **game time** -- milliseconds of Doom, accumulated from
the tics actually advanced -- rather than on the wall clock. In real-time mode the
loop paces itself so game time tracks wall time, which is what makes model latency
cost real Doom time. In fast mode game time runs ahead freely, so a smoke run
finishes in seconds while the interval schedule still means exactly what it means
during a live episode. Scheduling on the wall clock instead made a fast run with an
instant policy fire roughly one decision per episode.
"""

from __future__ import annotations

import math
import statistics
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from . import actions
from .client import Decision, DecisionClient, DecisionError
from .state import Observation, from_game_state, serialize

# Doom's clock. ViZDoom's default is 35 tics per second.
TICS_PER_SECOND = 35
MS_PER_TIC = 1000.0 / TICS_PER_SECOND

# Cadence is expressed in tics, not milliseconds, because Doom's clock is 35 tics
# per second and 10 Hz is not expressible on it: 100 ms is 3.5 tics. An interval
# that is not a whole number of tics expires a fraction before the loop next looks
# at the world, so every applied action decayed to neutral after a single tick and
# play came out far more sluggish than the latency warranted.
#
# 4 tics = 114.3 ms = 8.75 decisions/sec, the nearest safe alignment to the
# reference demo's 10 Hz given a measured p95 of 76 ms and a worst case of 99 ms.
DECISION_INTERVAL_TICS = 4
DECISION_INTERVAL_MS = DECISION_INTERVAL_TICS * MS_PER_TIC

# Doom turns 2.64 degrees per tic (measured), so one decision interval sweeps only
# 10.6 degrees. That is not a search: the model re-decides every interval and can
# reverse, leaving the view oscillating inside a narrow arc.
#
# A chosen `scan` therefore commits to a whole sweep -- one direction, at least 30
# degrees -- surviving the normal per-interval decay. Holding the direction is
# execution of the model's intent, in the same category as rendering `scan` as a
# turn at all; a sweep that reverses every interval is not a sweep. The model still
# decides *whether* to search, and any other answer cancels the commitment at once.
TURN_DEGREES_PER_TIC = 2.64
SWEEP_DEGREES = 30.0
SWEEP_TICS = int(math.ceil(SWEEP_DEGREES / TURN_DEGREES_PER_TIC))  # 12 tics, ~343 ms
SWEEP_MS = SWEEP_TICS * MS_PER_TIC
SCAN_ANSWER = "scan"
WARMUP_CALLS = 2  # the first call measured 686 ms cold; never let that hit a live episode


@dataclass
class TickRecord:
    """One published tick. What the UI draws and the transcript keeps."""

    tick: int
    tics_advanced: int
    state: dict
    action: list[int]
    buttons: list[str]
    fresh: bool          # a reply landed on this tick rather than the latch coasting
    sweeping: bool       # a committed scan is still turning
    decision: Decision | None
    health: float
    ammo: float
    killcount: float
    frame: Any = field(default=None, repr=False)


@dataclass
class EpisodeResult:
    """How an episode went, in the terms the demo actually claims."""

    ticks: int
    game_tics: int
    score: float
    killcount: float
    decisions: int
    applied: int
    skipped_slots: int
    stale_replies: int
    errors: int
    sweeps: int = 0
    sweeps_interrupted: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def latency_p50(self) -> float | None:
        return statistics.median(self.latencies_ms) if self.latencies_ms else None

    @property
    def latency_p95(self) -> float | None:
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        return ordered[max(0, int(0.95 * len(ordered)) - 1)]

    @property
    def decisions_per_second(self) -> float | None:
        seconds = self.game_tics / TICS_PER_SECOND
        return self.decisions / seconds if seconds else None

    def summary(self) -> str:
        p50 = "n/a" if self.latency_p50 is None else f"{self.latency_p50:.1f} ms"
        p95 = "n/a" if self.latency_p95 is None else f"{self.latency_p95:.1f} ms"
        rate = "n/a" if self.decisions_per_second is None else f"{self.decisions_per_second:.1f}/s"
        return (
            f"score={self.score:.0f} kills={self.killcount:.0f} "
            f"decisions={self.decisions} ({rate}) applied={self.applied} "
            f"skipped={self.skipped_slots} stale={self.stale_replies} "
            f"sweeps={self.sweeps}/{self.sweeps_interrupted}int errors={self.errors} "
            f"latency p50={p50} p95={p95}"
        )


class ActionLatch:
    """Holds the most recent reply for one interval, then lets go.

    Pure logic with an injected clock so the timing rules can be tested without
    a Doom process or real latency.
    """

    def __init__(
        self,
        buttons: Sequence[str],
        *,
        interval_ms: float = DECISION_INTERVAL_MS,
        sweep_ms: float = SWEEP_MS,
    ) -> None:
        self._buttons = list(buttons)
        self._interval_ms = interval_ms
        self._sweep_ms = sweep_ms
        self._action = actions.neutral(buttons)
        self._expires_at = 0.0
        self._generation = 0
        self.stale_replies = 0
        # A committed sweep outlives the ordinary one-interval decay.
        self._sweep_expires_at = 0.0
        self.sweeps_started = 0
        self.sweeps_interrupted = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def sweeping(self) -> bool:
        return self._sweep_expires_at > 0.0

    def sweep_remaining_ms(self, now_ms: float) -> float:
        return max(0.0, self._sweep_expires_at - now_ms)

    def bump_generation(self) -> int:
        """Invalidate every reply now in flight. Called when an episode restarts."""
        self._generation += 1
        self._action = actions.neutral(self._buttons)
        self._expires_at = 0.0
        self._sweep_expires_at = 0.0
        return self._generation

    def apply(self, decision: Decision, generation: int, now_ms: float, *, fire_threshold: float) -> bool:
        """Latch a reply. Returns False if it belongs to a superseded episode."""
        if generation != self._generation:
            self.stale_replies += 1
            return False

        turn = decision.get("turn")
        wants_scan = turn is not None and str(turn.value) == SCAN_ANSWER

        if wants_scan:
            # Start a sweep, or let one already running continue. Continuing rather
            # than restarting is what keeps a sweep to one direction and one arc.
            if not self.sweeping:
                self._sweep_expires_at = now_ms + self._sweep_ms
                self.sweeps_started += 1
        elif self.sweeping:
            # Anything else means the model has something better to do than search.
            # Abandon the arc immediately rather than finishing it first.
            self._sweep_expires_at = 0.0
            self.sweeps_interrupted += 1

        self._action = actions.from_decision(self._buttons, decision, fire_threshold=fire_threshold)
        self._expires_at = now_ms + self._interval_ms
        return True

    def current(self, now_ms: float) -> list[int]:
        """The buttons to press now.

        A committed sweep keeps its action past the ordinary interval decay, so the
        turn covers real ground instead of stuttering for 10 degrees at a time.
        """
        if self.sweeping:
            if now_ms < self._sweep_expires_at:
                return list(self._action)
            self._sweep_expires_at = 0.0
        if now_ms >= self._expires_at:
            self._action = actions.neutral(self._buttons)
        return list(self._action)


class MonotonicClock:
    """Wall clock in milliseconds."""

    def now_ms(self) -> float:
        import time

        return time.perf_counter() * 1000

    def sleep_ms(self, duration: float) -> None:
        import time

        if duration > 0:
            time.sleep(duration / 1000)

    def advance_ms(self, duration: float) -> None:
        """Book game time without waiting. Real time passes on its own."""
        return None


class ManualClock:
    """Test clock. ``sleep_ms`` advances time instead of waiting."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now_ms(self) -> float:
        return self.t

    def sleep_ms(self, duration: float) -> None:
        self.t += max(0.0, duration)

    def advance_ms(self, duration: float) -> None:
        self.t += max(0.0, duration)

    def advance(self, duration: float) -> None:
        self.t += duration


class DecisionLoop:
    """Drives one ViZDoom game with one decision backend."""

    def __init__(
        self,
        game: Any,
        client: DecisionClient,
        questions: dict[str, dict],
        *,
        interval_ms: float = DECISION_INTERVAL_MS,
        fire_threshold: float = actions.FIRE_THRESHOLD,
        clock: Any | None = None,
        real_time: bool = True,
        use_thread: bool = True,
        crosshair_tolerance_px: int = 0,
        sweep_ms: float = SWEEP_MS,
        goal_x: float | None = None,
    ) -> None:
        self.game = game
        self.client = client
        self.questions = questions
        # Snap the interval to whole tics so the latch and the game clock line up.
        self._interval_tics = max(1, int(round(interval_ms / MS_PER_TIC)))
        self.interval_ms = self._interval_tics * MS_PER_TIC
        self.fire_threshold = fire_threshold
        self.crosshair_tolerance_px = crosshair_tolerance_px
        self.goal_x = goal_x
        self.clock = clock or MonotonicClock()
        # When False the loop does not sleep to fill an interval -- for tests and
        # for replaying an episode as fast as the model can answer.
        self.real_time = real_time
        # Inline dispatch removes the worker thread, which makes tests deterministic:
        # a reply is always ready on the tick it was requested.
        self.use_thread = use_thread

        self.buttons = actions.button_names(game)
        self.latch = ActionLatch(self.buttons, interval_ms=self.interval_ms, sweep_ms=sweep_ms)
        # Milliseconds of Doom elapsed this episode. The single time base.
        self._game_ms = 0.0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="laya") if use_thread else None
        self._inflight: Future | None = None
        self._inflight_generation = 0
        self._lock = threading.Lock()
        self.errors: list[str] = []

    # -- model dispatch ----------------------------------------------------

    def warmup(self, state: dict, calls: int = WARMUP_CALLS) -> None:
        """Pay the cold-start cost before the episode starts, not during it."""
        for _ in range(calls):
            try:
                self.client.decide(state, self.questions)
            except Exception as exc:
                # A backend that cannot answer at all should say so now rather than
                # let an episode run to completion making no decisions.
                raise DecisionError(f"warmup failed: {type(exc).__name__}: {exc}") from exc

    def _dispatch(self, state: dict) -> None:
        self._inflight_generation = self.latch.generation
        if self._executor is not None:
            self._inflight = self._executor.submit(self.client.decide, state, self.questions)
            return
        future: Future = Future()
        try:
            future.set_result(self.client.decide(state, self.questions))
        except Exception as exc:
            future.set_exception(exc)
        self._inflight = future

    def _collect(self, now_ms: float) -> tuple[Decision | None, bool]:
        """Take a finished reply, if there is one. Returns (decision, applied)."""
        future = self._inflight
        if future is None or not future.done():
            return None, False
        self._inflight = None
        try:
            decision = future.result()
        except DecisionError as exc:
            self.errors.append(str(exc))
            return None, False
        except Exception as exc:  # a backend bug must not kill the episode
            self.errors.append(f"{type(exc).__name__}: {exc}")
            return None, False
        applied = self.latch.apply(decision, self._inflight_generation, now_ms, fire_threshold=self.fire_threshold)
        return decision, applied

    # -- the loop ----------------------------------------------------------

    def run_episode(
        self,
        *,
        max_ticks: int | None = None,
        on_tick: Callable[[TickRecord], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> EpisodeResult:
        self.game.new_episode()
        self.latch.bump_generation()

        observation = self._observe()
        if observation is not None:
            self.warmup(serialize(observation))

        result = EpisodeResult(ticks=0, game_tics=0, score=0.0, killcount=0.0,
                               decisions=0, applied=0, skipped_slots=0, stale_replies=0, errors=0)
        self._game_ms = 0.0
        wall_start_ms = self.clock.now_ms()
        next_slot_ms = 0.0
        tick = 0

        while not self.game.is_episode_finished():
            if max_ticks is not None and tick >= max_ticks:
                break
            if should_stop is not None and should_stop():
                break

            now_ms = self._game_ms
            observation = self._observe()
            if observation is None:
                break
            state = serialize(observation)

            next_slot_ms = self._service_slot(now_ms, next_slot_ms, state, result)

            decision, applied = self._collect(now_ms)
            if applied:
                result.applied += 1

            action = self.latch.current(now_ms)
            tics = self._tics_to_advance(wall_start_ms)
            # set_action then advance_action, not advance_action alone:
            # advance_action takes no buttons, so omitting set_action advances the
            # world with nothing pressed and the policy silently never acts.
            self.game.set_action(action)
            self.game.advance_action(tics, True)

            tick += 1
            result.ticks = tick
            result.game_tics += tics
            if decision is not None:
                result.latencies_ms.append(decision.latency_ms)

            if on_tick is not None:
                on_tick(TickRecord(
                    tick=tick,
                    tics_advanced=tics,
                    state=state,
                    action=action,
                    buttons=self.buttons,
                    fresh=applied,
                    sweeping=self.latch.sweeping,
                    decision=decision,
                    health=observation.health,
                    ammo=observation.ammo,
                    killcount=observation.killcount,
                    frame=self._frame(),
                ))

        result.score = self.game.get_total_reward()
        result.killcount = self._last_killcount
        result.stale_replies = self.latch.stale_replies
        result.sweeps = self.latch.sweeps_started
        result.sweeps_interrupted = self.latch.sweeps_interrupted
        result.errors = len(self.errors)
        return result

    def _service_slot(self, now_ms: float, next_slot_ms: float, state: dict, result: EpisodeResult) -> float:
        """Dispatch if a slot is open, and return when the next slot falls due.

        A slot that opens while a request is still out is *skipped*, not queued:
        queueing would let the loop fall arbitrarily far behind, and the server
        would refuse the concurrent request anyway.
        """
        if now_ms < next_slot_ms:
            return next_slot_ms
        if self._inflight is None:
            self._dispatch(state)
            result.decisions += 1
        else:
            result.skipped_slots += 1
        missed = int((now_ms - next_slot_ms) // self.interval_ms) + 1
        return next_slot_ms + missed * self.interval_ms

    def _tics_to_advance(self, wall_start_ms: float) -> int:
        """How far Doom moves before the next look at the world.

        Real-time mode keeps game time level with wall time: whatever the model
        spent thinking has already passed in Doom, so a slow reply is paid for in
        the world moving on. If the loop is ahead of the wall clock it sleeps out
        the difference so the game does not run fast.

        Fast mode advances one interval's worth of tics per iteration and never
        sleeps, for smoke runs and CI.
        """
        if not self.real_time:
            tics = self._interval_tics
            self._game_ms += tics * MS_PER_TIC
            return tics

        wall_elapsed = self.clock.now_ms() - wall_start_ms
        behind_ms = wall_elapsed - self._game_ms
        if behind_ms < MS_PER_TIC:
            self.clock.sleep_ms(MS_PER_TIC - behind_ms)
            tics = 1
        else:
            tics = max(1, int(round(behind_ms / MS_PER_TIC)))
        self._game_ms += tics * MS_PER_TIC
        return tics

    # -- game access -------------------------------------------------------

    _last_killcount = 0.0

    def _observe(self) -> Observation | None:
        observation = from_game_state(
            self.game.get_state(), self.game,
            tolerance_px=self.crosshair_tolerance_px,
            goal_x=self.goal_x,
        )
        if observation is not None:
            self._last_killcount = observation.killcount
        return observation

    def _frame(self) -> Any:
        state = self.game.get_state()
        return None if state is None else state.screen_buffer

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
