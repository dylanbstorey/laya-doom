---
id: headless-real-time-decision-loop
level: task
title: "Headless real-time decision loop"
short_code: "LDOOM-T-0004"
created_at: 2026-09-23T02:45:27.563797+00:00
updated_at: 2026-09-23T02:59:12.796251+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/active"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# Headless real-time decision loop

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

The demo itself: LAYA plays a full Doom episode unattended at ~10 Hz, with no UI. Everything
before this was groundwork; everything after is presentation.

## Acceptance Criteria

## Acceptance Criteria **[REQUIRED]**

- [x] Loop holds a ~100 ms decision cadence, decoupled from engine tics via action repeat.
- [x] Latch: a reply applies for exactly one interval on arrival, then decays to neutral
      (REQ-004). A deliberately delayed stub reply proves the game clock does not desync.
- [x] At most one request in flight; a slot that opens while a request is pending is skipped,
      not queued (NFR-002).
- [x] Generation counter discards replies belonging to a previous episode (REQ-005).
- [x] `StubClient` with fixed answers runs a full episode with no model, for CI and for
      isolating loop bugs from model behaviour.
- [x] Answer-to-button mapping unit tested against synthetic answers (REQ-003).
- [x] Every tick appends a decision record: state text, answers, distributions, latency.
- [x] A full `defend_the_center` episode completes live against `laya-mps`.
- [x] Episode score reported next to a scripted baseline and a random baseline (NFR-004).
- [x] Observed p50/p95 latency printed at episode end (NFR-001).

## Test Cases **[CONDITIONAL: Testing Task]**

### Test Case 1: Slow reply degrades smoothly
- **Test ID**: TC-001
- **Preconditions**: `StubClient` with a 250 ms artificial delay.
- **Steps**: run 100 ticks.
- **Expected Results**: episode completes; actions go neutral between replies; no queue growth;
  no crash. Sluggish play is the correct failure mode.

### Test Case 2: Stale reply discarded
- **Test ID**: TC-002
- **Preconditions**: stub whose reply arrives after an episode restart.
- **Steps**: dispatch, restart the episode, let the reply land.
- **Expected Results**: reply is dropped; the new episode never acts on it.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
Port the structure of `laya-mps`'s `decisions.mjs` — `INTERVAL`, `inflight`, `generation`,
`actionUntil` — to Python. It is a proven solution to this exact problem; reinventing it would
be perverse.

The loop is synchronous and single-threaded: ViZDoom advances only when we call `make_action`,
so there is no wall-clock pressure while waiting on the model. Cadence is measured in engine
tics (35 tics/sec default, so ~3-4 tics per 100 ms interval) rather than real time, which makes
episodes reproducible.

### Dependencies
[[LDOOM-T-0001]], [[LDOOM-T-0002]], [[LDOOM-T-0003]].

### Risk Considerations
Baselines may embarrass the model, and should be reported anyway (NFR-004) — the demo's claim is
about latency and calibration, not Doom skill. Burying the comparison would make the demo
dishonest; publishing it is the whole point.

## Status Updates **[REQUIRED]**

### 2026-09-22 — complete

`src/laya_doom/loop.py`, `actions.py`, `baselines.py`, `game.py`, `play.py`.
**103 tests passing.** LAYA plays unattended `defend_the_center` episodes end to end.

**Measured, 6 episodes per policy** (M1 Max, `--memory full --question-batch-size 4`):

| policy | mean score | kills | decisions/s | p50 | p95 | skipped slots |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| laya | 0.3 | 1.3 | 8.8 | **46.6 ms** | 66.0 ms | 0 |
| scripted | 0.3 | 1.3 | 8.8 | — | — | 0 |
| random | **1.2** | **2.2** | 8.8 | — | — | 0 |

NFR-001 met with room to spare — p50 46.6 ms against a 114 ms interval, and **zero skipped
slots** across every episode, so the loop never once fell behind. Live p50 is *lower* than the
62.1 ms measured in [[LDOOM-T-0003]] because many live ticks have no enemy in sight, and a
shorter state text is fewer tokens.

**Finding — random beats both, and LAYA exactly ties the scripted policy.** Instrumented action
rates explain it:

| policy | fire rate | turn = hold | crosshair on an enemy |
| --- | ---: | ---: | ---: |
| scripted | 7.5% | 81% | 6.5% of ticks |
| laya | 12.2% | 88% | 5.7% of ticks |
| random | **45.3%** | 34% | 3.2% of ticks |

The crosshair sits on an enemy only ~6% of ticks, so a policy that fires only when lined up
fires almost never, while random sprays six times as many shots and gets more kills in a
scenario that surrounds the player with large, close targets. So the honest statement is sharper
than "LAYA plays Doom badly": **LAYA faithfully reproduces the scripted reference policy, and
that policy loses to noise in this scenario.** The model is doing its job; the policy is what is
weak. The scripted baseline is a *reference*, not the ceiling NFR-004 assumed — worth correcting
in [[LDOOM-T-0006]].

**Three real bugs found and fixed here:**

1. **The action never reached the game.** `advance_action(tics, True)` takes no buttons, so
   omitting `set_action` advanced the world with nothing pressed. Every policy scored -1 with 0
   kills and looked incompetent; nothing was ever pressed. Now pinned by
   `test_the_action_actually_reaches_the_game`, which asserts a non-neutral action reaches a fake
   game — this is precisely the class of bug that is invisible from watching gameplay.
2. **Cadence must be expressed in tics, not milliseconds.** Doom's clock is 35 tics/sec, so 10 Hz
   is 3.5 tics and is not expressible. A 100 ms interval expired a fraction before the loop next
   looked at the world, so every applied action decayed to neutral after a single tic and play was
   far more sluggish than the latency warranted. The interval now snaps to whole tics; the default
   is 4 tics = 114.3 ms = **8.75 decisions/sec**, the nearest safe alignment to the reference
   demo's 10 Hz given a p95 of 66 ms.
3. **Scheduling on the wall clock broke fast mode.** Game time advanced in tics while slots were
   scheduled on wall time, so a fast run with an instant policy fired roughly one decision per
   episode. Everything now schedules on **game time** accumulated from tics advanced; real-time
   mode paces itself so game time tracks wall time, which is what makes model latency cost real
   Doom time.

**Decisions:**

- The model is called on a **worker thread** while the game advances on the main thread. Blocking
  on each decision would have been easier, and dishonest: with the world frozen while the model
  thinks, latency costs nothing and the demo proves nothing about real-time control.
- Baselines are `DecisionClient` implementations, not separate loops, so they read the *same*
  serialized state dict at the same cadence through the same latch. Any gap is attributable to the
  decision procedure alone.
- Warmup failures raise immediately rather than running an episode that makes no decisions;
  failures *during* an episode are counted and the episode survives.
- `use_thread=False` added for deterministic tests — a threaded dispatch made reply timing racy.