---
id: committed-sweeps-forward-movement
level: task
title: "Committed sweeps, forward movement, and a full decision log"
short_code: "LDOOM-T-0008"
created_at: 2026-09-23T03:34:03.573656+00:00
updated_at: 2026-09-23T03:34:03.573656+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/todo"


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

## Acceptance Criteria **[REQUIRED]**

- [ ] A chosen `scan` commits to **at least 30 degrees** of rotation (>= 12 tics) before the
      direction can change.
- [ ] A sweep never reverses mid-sweep; one sweep is one direction.
- [ ] A sweep aborts immediately when a decision other than `scan` arrives, so spotting an enemy
      interrupts the search rather than finishing the arc first.
- [ ] `advance` is available as an action and maps to `MOVE_FORWARD`, letting the model close on
      a lined-up but distant enemy.
- [ ] `MOVE_FORWARD` is added to the scenario's buttons (`defend_the_center.cfg` exposes only
      TURN_LEFT/TURN_RIGHT/ATTACK; verified that adding it works and moves 3.3 units/tic).
- [ ] The scripted baseline gets the same action space, so the comparison stays fair.
- [ ] The question schema is re-benched; `advance` ships only if it scores.
- [ ] The UI shows a scrolling log of **every** decision, not just the current one, with tick,
      answers, confidence and latency.
- [ ] The UI shows sweep state and skipped slots, so a committed sweep is legible rather than
      looking like a frozen panel.
- [ ] A 503 from the single-slot decision server is retried rather than failing warmup.

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

*To be added during implementation*
