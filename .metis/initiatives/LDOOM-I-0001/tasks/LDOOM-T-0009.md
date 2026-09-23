---
id: deadly-corridor-navigation-and
level: task
title: "deadly_corridor: navigation and strafing"
short_code: "LDOOM-T-0009"
created_at: 2026-09-23T10:20:37.259234+00:00
updated_at: 2026-09-23T10:20:37.259234+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/todo"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# deadly_corridor: navigation and strafing

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Put LAYA in a scenario that is a different problem, not the same problem with more buttons.

`defend_the_center` is fixed-position aim-and-fire. `deadly_corridor` is navigation under fire:
seven buttons including strafing, reward is distance travelled toward a vest **1312 units** away,
dying costs **100**, and the scenario ships at `doom_skill 5` — the hardest.

## Requirements

### System Requirements
- **Functional Requirements**
  - REQ-101: Per-scenario configuration — action space, question battery, cadence, game variables.
  - REQ-102: State reports progress toward the goal, in words and as a percentage.
  - REQ-103: Corridor action space: advance, hold, aim left/right, dodge left/right, retreat.
  - REQ-104: Baselines for the corridor's action space, including the blind "walk forward" bar.
- **Non-Functional Requirements**
  - NFR-101: Decision p50 inside the scenario's own interval, reported honestly.
  - NFR-102: The corridor state must stay inside the 1024-token context; it runs longer than
    `defend_the_center`'s (608-724 chars against 400-550) because it carries the journey.

## Use Cases **[CONDITIONAL: User-Facing Initiative]**

### Use Case 1: Compare scenarios
- **Actor**: the author
- **Scenario**: `uv run python play.py --scenario deadly_corridor --policy all`
- **Expected Outcome**: LAYA against scripted, random, and walk-forward, on one scoreboard.

## Architecture **[CONDITIONAL: Technically Complex Initiative]**

### Overview
A `Scenario` dataclass in `scenarios.py` holds everything that varies: battery, cadence in tics,
game variables, extra buttons, and `goal_x`. `game.py`, `loop.py` and `play.py` take a `Scenario`
rather than a scenario name, so adding a third map is a data change.

## Detailed Design **[REQUIRED]**

**Measured before designing.** Reward tracks distance along +X almost exactly; the `GreenArmor`
vest that marks the end is visible in the label buffer from the first tick, at x=1312. Walking
forward blindly and dying partway scores **+528 to +772** depending on the run. That, not zero,
is the bar — and it is a genuinely awkward bar, because the reward structure pays for recklessness
right up until the 100-point death penalty lands.

**One seven-option question, not two questions.** Latency is the binding constraint —
`defend_the_center` already runs at 5.2 decisions/sec against a possible 8.75 — so aiming and
moving share a single `choice` rather than getting one question each. `fire` stays separate, so
the model can shoot while doing any of them.

**5-tic cadence (142.9 ms) instead of 4.** The corridor question carries seven criteria and the
state carries the journey, so both are longer to tokenise. A corridor is also less frantic than
being surrounded. Buy the headroom rather than skip slots.

**Criteria written out in full**, per the finding in [[LDOOM-T-0008]]: compressing them cost more
than half the score by making options unreachable.

## Alternatives Considered **[REQUIRED]**

- **Separate `aim` and `move` questions** — cleaner semantics, but a third question costs more
  decisions than the finer control buys at the measured latency.
- **`deathmatch`** — 20 buttons, weapon selection, items. The bigger jump, and weapon choice is a
  natural typed decision; deferred so the corridor's navigation findings can de-risk it.
- **Reusing the `defend_the_center` battery unchanged** — it has no vocabulary for strafing,
  retreating or a destination, so the model could not express the decisions the map is about.

## Implementation Plan **[REQUIRED]**

1. `scenarios.py`, and make `game.py` / `loop.py` / `play.py` scenario-aware.
2. Goal-aware state: `progress`, `distance_to_goal`, a journey phrase.
3. `CORRIDOR_BATTERY` and a unified answer -> button table.
4. Corridor baselines: scripted, random, walk-forward.
5. Measure against all three; report honestly whether LAYA beats walking forward.
6. Scenario selector in the web UI.

## Status Updates **[REQUIRED]**

### 2026-09-23 — built, measuring

Discovery, all measured rather than assumed:

| fact | value |
| --- | --- |
| corridor length | 1312 units (vest visible in the label buffer from tick 0) |
| reward | tracks distance along +X; death costs 100 |
| default difficulty | `doom_skill 5`, the hardest |
| walk forward blindly | dies at x=683-834, scores **+528 to +772** |
| walk forward at skill 1 | reaches the vest, +2281 |
| corridor state text | 608-724 chars, against 400-550 for `defend_the_center` |

Built: `scenarios.py`, goal-aware `state.py`, `CORRIDOR_BATTERY`, unified `ANSWER_BUTTONS`,
three corridor baselines, scenario-aware `play.py`. 124 tests still passing.

The 503 retry from [[LDOOM-T-0008]] proved itself immediately: with the web app still playing in
a browser, the corridor run failed with a clear "stop the other run" message instead of a crash.

**Open:** LAYA's corridor scoreboard; scenario selector in the web UI; tests for the corridor
action mapping and goal state.
