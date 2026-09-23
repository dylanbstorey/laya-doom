---
id: question-schema-fixture-bench
level: task
title: "Question schema fixture bench"
short_code: "LDOOM-T-0003"
created_at: 2026-09-23T02:45:27.548270+00:00
updated_at: 2026-09-23T02:59:12.783015+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/completed"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# Question schema fixture bench

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Choose the shipped question battery by measurement. Discovery produced one question that worked
(`fire`, 0.897) and one that did not (`turn`, confidence 0.0115) on the first attempt, so schema
selection is an experiment with a scoreboard, not a design decision to be made once.

## Acceptance Criteria

## Acceptance Criteria

## Acceptance Criteria **[REQUIRED]**

- [x] A fixture set of serialized states, each hand-labelled with the correct action.
- [x] Fixtures cover: enemy centred, enemy left, enemy right, no enemy visible, multiple enemies,
      low health, out of ammo.
- [x] `bench/score.py` runs candidate schemas over the fixtures and reports, per question,
      accuracy against the label and mean confidence.
- [x] At least three candidate phrasings of `turn` compared, including the phrasing the probe
      showed failing, so the improvement is demonstrated rather than asserted.
- [x] Results committed as a table; the winning battery becomes `questions.py`.
- [x] Battery is <= 4 questions (NFR-003) and per-call latency is recorded alongside accuracy,
      since a schema that is accurate but too slow fails NFR-001.
- [x] If no phrasing beats chance on a question, that is recorded as a finding and the question
      is cut rather than shipped broken.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
Offline and deterministic — no Doom process, just saved state dicts through `DecisionClient`.
Fast to iterate and re-runnable when `laya-mps` changes.

Report mean confidence next to accuracy. A model that is right 60% of the time and *says* it is
unsure is a better demo than one right 65% of the time while claiming certainty — calibration is
the thing being shown off.

### Dependencies
[[LDOOM-T-0001]] (client), [[LDOOM-T-0002]] (states to label).

### Risk Considerations
The real possibility, given the probe: LAYA cannot do the `turn` decision at any phrasing. If so,
the honest response is to cut `turn`, let the demo be fire-control only, and say so in the README
— not to quietly compute the turn in Python and present it as the model's choice. That would
violate the vision's "the model decides, the code does not" principle.

## Status Updates **[REQUIRED]**

### 2026-09-22 — complete

`src/laya_doom/questions.py`, `bench/score.py`, `bench/threat.py`, results in `bench/results.md`.
40 states across 7 situations, each rendered two ways, 9 candidate questions.

**The shipped battery is two questions, not three.**

| Question | Winner | Score | Runners-up |
| --- | --- | ---: | --- |
| `fire` | `FIRE_QUESTION` | **97% balanced** | statement 71%, waste 69% |
| `turn` | `TURN_CRITERIA_LED` | **98%** | directive 85%, terse 72% |
| `threat` | — | **cut** | all three phrasings flat |

Measured latency for the shipped battery over 60 real states: **p50 62.1 ms**, p95 76.2 ms,
max 98.6 ms. NFR-001 met with 38% headroom at p50.

**Finding — raw accuracy was misleading for `fire`.** `fire=True` occurs in only 5/40 states, so
"always no" scores 88% raw. Balanced accuracy (always-no = 50%) tells the real story: all three
variants have 100% recall and differ only in specificity — 94% for `fire_question` against 43%
and 37% for the statement-shaped phrasings, which effectively hold the trigger down. Had this
gone unchecked, `fire_statement`'s 50% raw accuracy would have looked merely mediocre instead of
revealing a model that fires at nothing 20 times out of 35.

**Finding — the phrasing that reads best is not the one that works.** `fire` was written as a
*statement* on the theory that `noul` estimates whether statements are true. The question-shaped
phrasing ("The player should pull the trigger right now.") beat it by 26 points of balanced
accuracy. Similarly `turn` works best when the left/right mapping lives in the **criteria** rather
than the instructions — 98% vs 85%.

**Finding — `threat` does not track danger.** Three phrasings, paired health sweep holding geometry
fixed (`bench/threat.py`), health 100 -> 5 on a 0-2 scale: spans of +0.17, +0.14, +0.11. A player
at 5 health reads as barely more endangered than one at full health. Cut per the task's own
criterion rather than shipped broken; it also returns a third of the frame budget. This removes
the only `score`-type question from the demo, so the UI now shows `noul` and `choice` only —
noted for [[LDOOM-T-0005]].

**Finding — the `degrees` control is not uniformly worse.** It *beat* prose on the
statement-shaped `fire` variants (90% and 98% raw), probably because a bare "in crosshair" token
maps more directly onto a claim than a sentence does. But on `turn`, the question that actually
needs a spatial relation, prose scored 98% against degrees' 52%. That single gap is what
justifies `state.py`, and it is a narrower justification than [[LDOOM-T-0001]] assumed.

**Deviation from the acceptance criteria:** fixtures are labelled by a mechanically derived
oracle in `bench/score.py`, not by hand. The oracle is a hand-written function whose output was
eyeballed across situations, and deriving it keeps the bench reproducible. Worth stating plainly
that this makes the bench a test of *recoverability from prose* — Python already knows the right
answer. That is the same honest tension the reference demo has, and [[LDOOM-T-0006]] must say so.

**Also measured:** prose states cost more latency than degrees states (230 ms vs 156 ms for a
7-question probe request) because they are longer. Irrelevant at the shipped battery size, but it
is why the state text is kept to ~400 chars.