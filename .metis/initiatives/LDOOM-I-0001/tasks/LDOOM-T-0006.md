---
id: readme-and-demo-capture
level: task
title: "README and demo capture"
short_code: "LDOOM-T-0006"
created_at: 2026-09-23T02:45:36.201819+00:00
updated_at: 2026-09-23T02:45:36.201819+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/todo"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# README and demo capture

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Make the repo clonable and the result shareable, with numbers measured on this machine rather
than borrowed from anyone's marketing.

## Acceptance Criteria **[REQUIRED]**

- [ ] README states what this is: LAYA, an open-weights System 1 model, in Doom's control loop,
      after TypeSafe's Jev demo.
- [ ] Credits `laya-mps` (MIT), `laya` weights (Apache 2.0), ViZDoom, and the Jev demo as prior
      art; notes that the pong demo is where the loop pattern came from.
- [ ] Setup: clone, `uv sync`, start `laya-mps`, `./run.sh`. Verified from a clean clone.
- [ ] Measured latency table from this hardware (M1 Max), explicitly not the M5 Pro figures in
      the `laya-mps` README.
- [ ] States plainly that LAYA plays Doom badly, with the baseline comparison to show it.
- [ ] Documents the observation/decision line: which geometry Python computes and which choices
      the model makes, so nobody has to guess how much of it is real.
- [ ] Records the `turn`-question finding from the bench, including whether it was cut.
- [ ] A captured clip or GIF of the panel running.
- [ ] `git init`, sensible `.gitignore` (venv, HF cache, captures), and an initial commit.

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

*To be added during implementation*
