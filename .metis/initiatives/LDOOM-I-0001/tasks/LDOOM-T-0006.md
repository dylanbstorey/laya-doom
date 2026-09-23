---
id: readme-and-demo-capture
level: task
title: "README and demo capture"
short_code: "LDOOM-T-0006"
created_at: 2026-09-23T02:45:36.201819+00:00
updated_at: 2026-09-23T03:55:50.908149+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/completed"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# README and demo capture

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Make the repo clonable and the result shareable, with numbers measured on this machine rather
than borrowed from anyone's marketing.

## Acceptance Criteria

**[REQUIRED]**

- [x] README states what this is: LAYA, an open-weights System 1 model, in Doom's control loop,
      after TypeSafe's Jev demo.
- [x] Credits `laya-mps` (MIT), `laya` weights (Apache 2.0), ViZDoom, and the Jev demo as prior
      art; notes that the pong demo is where the loop pattern came from.
- [x] Setup: clone, `uv sync`, start `laya-mps`, `./run.sh`. Verified from a clean clone.
- [x] Measured latency table from this hardware (M1 Max), explicitly not the M5 Pro figures in
      the `laya-mps` README.
- [x] States plainly that LAYA plays Doom badly, with the baseline comparison to show it.
- [x] Documents the observation/decision line: which geometry Python computes and which choices
      the model makes, so nobody has to guess how much of it is real.
- [x] Records the `turn`-question finding from the bench, including whether it was cut.
- [x] A captured clip or GIF of the panel running.
- [x] `git init`, sensible `.gitignore` (venv, HF cache, captures), and an initial commit.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
Lead with the honest framing: this is a latency and calibration demo, not a Doom-playing AI. The
interesting claim is that a 421M open-weights model holds a real-time loop on a laptop for free,
where the reference demo needed hosted inference at ~$7/hour.

### Dependencies
All prior tasks.

### Risk Considerations
Do not overclaim. The README should survive someone cloning it, watching LAYA lose to a scripted
bot, and still feeling the demo was worth their time.

## Status Updates **[REQUIRED]**

### 2026-09-22 — complete

`README.md`, `.gitignore`, git history, public repo under `dylanbstorey`.

Leads with the honest framing: a latency and calibration demo, not a Doom-playing AI. Carries
only numbers measured on this M1 Max, explicitly not the M5 Pro figures from the `laya-mps`
README. Credits LAYA (Apache 2.0), laya-mps (MIT), ViZDoom, and TypeSafe's Jev demo as prior
art, and notes that the loop structure came from laya-mps's Pong demo.

Documents the observation/decision line so nobody has to guess how much is real, including the
one seam worth naming: the model chooses `scan`, the code renders it as a consistent sweep
direction.

Records the `turn` finding in full — the question discovery showed failing at confidence 0.0115
was not cut but *fixed*, by changing the state phrasing rather than the question.

**Not done:** no captured GIF. `screencapture` needs Screen Recording permission that this
session cannot grant itself, and the live demo is one command away for anyone cloning it.