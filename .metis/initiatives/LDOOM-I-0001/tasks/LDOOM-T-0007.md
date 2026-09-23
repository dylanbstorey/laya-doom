---
id: tuning-passes-to-raise-episode
level: task
title: "Tuning passes to raise episode score"
short_code: "LDOOM-T-0007"
created_at: 2026-09-23T03:16:13.228379+00:00
updated_at: 2026-09-23T03:16:13.228379+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/todo"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# Tuning passes to raise episode score

*This template includes sections for various types of tasks. Delete sections that don't apply to your specific use case.*

## Parent Initiative **[CONDITIONAL: Assigned Task]**

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

{Clear statement of what this task accomplishes}

## Backlog Item Details **[CONDITIONAL: Backlog Item]**

{Delete this section when task is assigned to an initiative}

### Type
- [x] Bug - Production issue that needs fixing
- [x] Feature - New functionality or enhancement  
- [x] Tech Debt - Code improvement or refactoring
- [x] Chore - Maintenance or setup work

### Priority
- [x] P0 - Critical (blocks users/revenue)
- [x] P1 - High (important for user experience)
- [x] P2 - Medium (nice to have)
- [x] P3 - Low (when time permits)

### Impact Assessment **[CONDITIONAL: Bug]**
- **Affected Users**: {Number/percentage of users affected}
- **Reproduction Steps**: 
  1. {Step 1}
  2. {Step 2}
  3. {Step 3}
- **Expected vs Actual**: {What should happen vs what happens}

### Business Justification **[CONDITIONAL: Feature]**
- **User Value**: {Why users need this}
- **Business Value**: {Impact on metrics/revenue}
- **Effort Estimate**: {Rough size - S/M/L/XL}

### Technical Debt Impact **[CONDITIONAL: Tech Debt]**
- **Current Problems**: {What's difficult/slow/buggy now}
- **Benefits of Fixing**: {What improves after refactoring}
- **Risk Assessment**: {Risks of not addressing this}

## Acceptance Criteria **[REQUIRED]**

- [x] {Specific, testable requirement 1}
- [x] {Specific, testable requirement 2}
- [x] {Specific, testable requirement 3}

## Test Cases **[CONDITIONAL: Testing Task]**

{Delete unless this is a testing task}

### Test Case 1: {Test Case Name}
- **Test ID**: TC-001
- **Preconditions**: {What must be true before testing}
- **Steps**: 
  1. {Step 1}
  2. {Step 2}
  3. {Step 3}
- **Expected Results**: {What should happen}
- **Actual Results**: {To be filled during execution}
- **Status**: Pass

### Test Case 2: {Test Case Name}
- **Test ID**: TC-002
- **Preconditions**: {What must be true before testing}
- **Steps**: 
  1. {Step 1}
  2. {Step 2}
- **Expected Results**: {What should happen}
- **Actual Results**: {To be filled during execution}
- **Status**: Pass

## Documentation Sections **[CONDITIONAL: Documentation Task]**

{Delete unless this is a documentation task}

### User Guide Content
- **Feature Description**: {What this feature does and why it's useful}
- **Prerequisites**: {What users need before using this feature}
- **Step-by-Step Instructions**:
  1. {Step 1 with screenshots/examples}
  2. {Step 2 with screenshots/examples}
  3. {Step 3 with screenshots/examples}

### Troubleshooting Guide
- **Common Issue 1**: {Problem description and solution}
- **Common Issue 2**: {Problem description and solution}
- **Error Messages**: {List of error messages and what they mean}

### API Documentation **[CONDITIONAL: API Documentation]**
- **Endpoint**: {API endpoint description}
- **Parameters**: {Required and optional parameters}
- **Example Request**: {Code example}
- **Example Response**: {Expected response format}

## Implementation Notes **[CONDITIONAL: Technical Task]**

{Keep for technical tasks, delete for non-technical. Technical details, approach, or important considerations}

### Technical Approach
{How this will be implemented}

### Dependencies
{Other tasks or systems this depends on}

### Risk Considerations
{Technical risks and mitigation strategies}

## Status Updates **[REQUIRED]**

### 2026-09-22 — the scan fix

Raised mean episode score from **+0.3 to +2.8** (4 episodes, `defend_the_center`, real time),
taking LAYA from *losing* to a random policy to beating it comfortably.

| policy | mean score | kills | decisions/s | p50 | skipped slots |
| --- | ---: | ---: | ---: | ---: | ---: |
| laya | **+2.8** | 3.8 | 6.9 | 76.8 ms | 20 |
| scripted | +9.0 | 10.0 | 8.7 | — | 0 |
| random | +1.5 | 2.5 | 8.8 | — | 0 |

**Root cause was mine, not the model's.** The shipped `hold` criterion read "the nearest enemy
is centred in the crosshair, **or no enemy is in sight**" — an instruction to stand still
whenever the view was empty. The model obeyed it, holding 88% of the time and waiting for
enemies to cross the view cone. Model accuracy was never the bottleneck: the battery already
scored 97-100% on `bench/score.py`.

**Fix, without letting code play the game:** added `scan` as a fourth option the model can
choose, narrowed `hold` to "already aimed, do not spoil the shot", and rewrote the empty-view
narration so searching is visibly available. `actions.py` renders a chosen `scan` as one
consistent turn direction — mechanical execution of the model's intent, not a decision. The
scripted baseline got the same option, because comparing a scanning model against a
non-scanning baseline would have flattered the model.

`turn_scan` scores **100%** on the fixture set, including `scan` on all six empty-view states.

**Finding — the scripted baseline was equally crippled, and is now the ceiling.** It went from
+0.3 to +9.0 with the same fix. The earlier conclusion in [[LDOOM-T-0004]] — that a
precision-aiming policy loses to spraying — was an artefact of both policies being told to
stand still. Corrected in the README.

**Finding — latency now shows up in the score.** LAYA manages 6.9 decisions/sec against the
baselines' 8.7, skipping ~20 slots per episode because p95 (99.8 ms) crowds the 114.3 ms
interval. Roughly a fifth of its chances to act are spent waiting on inference. That is the
honest price of a real model in the loop, and it is visible rather than hidden.

**Finding — pausing the world inflates results ~7x.** Synchronous mode scored +13/14 kills
against real time's +1/2 kills on the same seed, because a paused game gives unlimited
deliberation and removes every consequence of latency. `bench/tune.py` therefore sweeps in
real time despite being twice as slow. Tuning in synchronous mode would have optimised for a
regime the demo does not run in.

**Also:** trimming the empty-view narration from four sentences to two took p50 from 74 ms back
to 61 ms. Every token in the state is paid for on every tick.

**Not pursued** (stopped here at the user's request — "don't need perfect just this works"):
`bench/tune.py` is written and runs, but the fire-threshold, crosshair-tolerance and cadence
sweeps were not completed. Both knobs are wired and documented; a sweep is one command.