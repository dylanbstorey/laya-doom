---
id: committed-sweeps-forward-movement
level: task
title: "Committed sweeps, forward movement, and a full decision log"
short_code: "LDOOM-T-0008"
created_at: 2026-09-23T03:34:03.573656+00:00
updated_at: 2026-09-23T03:55:45.806047+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/completed"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# Committed sweeps, forward movement, and a full decision log

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Make searching actually cover ground, let the model close distance on far targets, and show every
decision in the UI rather than only the latest one.

A `scan` currently turns for a single 114 ms interval. **Measured: Doom turns 2.64 deg/tic**, so
one interval (4 tics) sweeps only **10.6 degrees** — and because the model re-decides every
interval it can reverse direction, leaving the view oscillating inside a narrow arc instead of
searching the room.

## Acceptance Criteria

**[REQUIRED]**

- [x] A chosen `scan` commits to **at least 30 degrees** of rotation (>= 12 tics) before the
      direction can change.
- [x] A sweep never reverses mid-sweep; one sweep is one direction.
- [x] A sweep aborts immediately when a decision other than `scan` arrives, so spotting an enemy
      interrupts the search rather than finishing the arc first.
- [x] `advance` is available as an action and maps to `MOVE_FORWARD`, letting the model close on
      a lined-up but distant enemy.
- [x] `MOVE_FORWARD` is added to the scenario's buttons (`defend_the_center.cfg` exposes only
      TURN_LEFT/TURN_RIGHT/ATTACK; verified that adding it works and moves 3.3 units/tic).
- [x] The scripted baseline gets the same action space, so the comparison stays fair.
- [x] The question schema is re-benched; `advance` ships only if it scores.
- [x] The UI shows a scrolling log of **every** decision, not just the current one, with tick,
      answers, confidence and latency.
- [x] The UI shows sweep state and skipped slots, so a committed sweep is legible rather than
      looking like a frozen panel.
- [x] A 503 from the single-slot decision server is retried rather than failing warmup.

## Test Cases **[CONDITIONAL: Testing Task]**

### Test Case 1: Sweep commitment
- **Test ID**: TC-001
- **Preconditions**: latch with a sweep budget of 12 tics, a `scan` decision applied.
- **Steps**: apply `scan`, advance past one interval, read the action repeatedly.
- **Expected Results**: the turn button stays pressed in one direction past the normal
  single-interval decay, for at least 30 degrees' worth of tics.

### Test Case 2: Spotting an enemy interrupts the sweep
- **Test ID**: TC-002
- **Preconditions**: a sweep in progress.
- **Steps**: apply a decision of `left`.
- **Expected Results**: the sweep is abandoned on the spot and the aim answer takes over.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
The commitment belongs in `ActionLatch`, which already owns "what buttons now". A sweep sets an
expiry measured in tics rather than intervals and survives the normal decay; any non-`scan`
decision clears it.

Holding a direction is execution of the model's `scan` intent, the same category as rendering
`scan` as a turn at all -- a sweep that reverses every interval is not a sweep. The model still
decides *whether* to search, and any other answer cancels it immediately. Worth stating in the
README next to the existing note about scan direction.

`advance` goes on the existing `turn` choice rather than becoming a third question: p95 latency
is already 99.8 ms against a 114.3 ms interval and 20 slots per episode are being skipped, so
another forward pass would cost more decisions than the action gains.

### Dependencies
[[LDOOM-T-0005]] for the panel, [[LDOOM-T-0007]] for the measured baseline this is compared to.

### Risk Considerations
- A 30 degree commitment is ~3 decision intervals during which the model's answers are ignored
  for the turn component. If an enemy appears at interval 1, TC-002 is what keeps that from
  costing a kill.
- `advance` could make the model walk into enemies and die faster. It ships only if the bench
  and an episode comparison support it; otherwise it is cut like `threat` was.

## Status Updates **[REQUIRED]**

### 2026-09-23 — sweeps and forward movement shipped

Pushed as `367ba47`. 124 tests.

**Measured first, then built.** Doom turns **2.64 deg/tic**, so one 4-tic interval sweeps only
**10.6 degrees** — an uncommitted `scan` was never going to search a room. `SWEEP_TICS = 12`
gives **31.7 degrees** per sweep, held across ~3 decision intervals, cancelled instantly by any
non-`scan` answer.

`MOVE_FORWARD` is not in `defend_the_center.cfg` (turn and attack only) but `add_available_button`
works: **3.3 units/tic** against an arena radius of ~812.

**`advance` is the one case where the fixture oracle and play disagree, and play won:**

| turn question | fixture accuracy | mean score | kills |
| --- | ---: | ---: | ---: |
| `scan` (4 options) | **100%** | +4.6 (sd 3.9) | 5.6 |
| `approach` (5 options) | 85% | **+13.4** (sd 5.1) | **14.4** |

The oracle claimed advancing is for "aimed but far away" shots and marked the model wrong 4
times for choosing `hold` instead. In play the value of `advance` is that **moving repositions
the player and finds enemies** — something a fixture, being one frozen tick, cannot express. The
oracle was measuring the wrong thing, so it is reported rather than obeyed. Recorded prominently
because it is a real limit on how much the offline bench can settle.

Honest caveat: `advance` is chosen only **~7%** of the time, so the 3x gain is not purely forward
movement — the whole answer mix shifted (`scan` 16% -> 24%, `left` 28% -> 14%).

**Correction — I over-attributed a latency regression.** I claimed the verbose five-option
criteria pushed p50 from ~77 ms to ~98 ms and cost ~40% of slots. The user pointed out the
machine was running other work, and they are right that this is a confound: the two question
forms were measured in separate runs at different times, so ambient load was never controlled.
An interleaved A/B (alternating forms request-by-request on identical states, so load falls on
both equally) is the correct experiment and is running. The claim in `questions.py` is being
softened to match whatever it shows.

Trimming input tokens is worth doing regardless, and the user confirmed that, so
`TURN_APPROACH_TERSE` ships once its accuracy is verified — a shorter question is re-tokenised
on every tick either way.

### 2026-09-23 — trimming the question text was rejected on measurement

The user asked to trim input tokens and I was about to. **The data said no**, so verbose ships.

| turn question | mean score | kills | `advance` | `scan` | `hold` |
| --- | ---: | ---: | ---: | ---: | ---: |
| verbose (shipped) | **+13.0** (sd 6.2) | 14.0 | 3% | 23% | 20% |
| terse | +5.6 (sd 4.6) | 6.6 | **0%** | 14% | 33% |

The latency saving is real and was verified properly: an interleaved A/B, alternating both forms
request-by-request on identical states so ambient load falls on both equally, gives p50 84.2 ms
verbose against 73.6 ms terse for a 30% smaller payload — **10.6 ms**. Terse also scored *higher*
confidence (0.105 vs 0.073), though lower fixture accuracy (75% vs 85%).

It still loses badly in play, and the answer distribution explains it: terse picks `advance`
**0%** of the time and scans 14% against 23%, with `hold` absorbing the difference. The verbose
criteria are load-bearing — "so walk forward to close the distance" and "keep turning to search
the room for one" are what make those options reachable. Compressed, the model reverts to
standing still, which is exactly the failure the original `hold` criterion caused. 194 characters
buy 7 points of score for 10 ms.

`TURN_APPROACH_TERSE` is kept in `questions.py` as the record of the experiment, not as a switch.

**Final scoreboard, 5 episodes per policy:**

| policy | mean score | kills | decisions/s | p50 | skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
| laya | **+8.0** | 9.0 | 5.2 | 98.5 ms | 65 |
| scripted | +12.4 | 13.4 | 8.8 | — | 0 |
| random | +1.0 | 2.0 | 8.8 | — | 0 |

LAYA at **65%** of the scripted reference, up from 31% before this task and 100%-of-a-broken-0.3
before `scan` existed. Verified over the websocket: 156/156 decisions logged, 52 ticks flagged
sweeping, all five turn options exercised, 6 sweeps with 3 interrupted by spotting an enemy.

**Task complete.**