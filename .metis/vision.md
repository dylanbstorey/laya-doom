---
id: laya-doom
level: vision
title: "laya-doom"
short_code: "LDOOM-V-0001"
created_at: 2026-09-23T02:38:07.903821+00:00
updated_at: 2026-09-23T02:41:08.687603+00:00
archived: false

tags:
  - "#vision"
  - "#phase/published"


exit_criteria_met: false
initiative_id: NULL
---

# LAYA Plays Doom — Vision

## Purpose **[REQUIRED]**

Demonstrate, on a laptop, that an open-weights System 1 decision model can hold down a
real-time control loop. TypeSafe showed this with Jev playing Doom at roughly 10 decisions
per second for about $7/hour of hosted inference. LAYA (`convaiinnovations/laya`, Apache 2.0,
421M params) is the same model class with open weights, so the same demo should run locally
for free. This project builds that demo.

## Product/Solution Overview **[CONDITIONAL: Product/Solution Vision]**

A local application with a browser UI. ViZDoom runs Doom in-process and exposes structured
game state. Each tick that state is serialized to text, handed to LAYA alongside a fixed set
of typed questions (`choice` / `score` / `noul`), and the returned typed answers are mapped
directly to key presses. The browser shows the Doom viewport next to a live decision panel:
every question, the chosen answer, its calibrated probability, and the per-decision latency.

Audience: the author and whoever he shows it to. Distribution ceiling is a public GitHub repo.

## Current State **[REQUIRED]**

- Jev's Doom demo exists but the model is closed and hosted; the loop costs ~$7/hour and
  cannot be inspected or modified.
- LAYA is published on Hugging Face with an Apache 2.0 license and a trivial Python API,
  but every published example is a text-routing task (support tickets, invoices, emails).
  Nothing demonstrates it inside a real-time loop.
- No code exists in this repo.

## Future State **[REQUIRED]**

`./run.sh` opens a browser and LAYA starts playing Doom. Decisions land in the tens of
milliseconds on Apple Silicon, the loop holds a steady cadence, and the decision panel makes
the model's reasoning legible frame by frame — including when it is confidently wrong.

## Major Features **[CONDITIONAL: Product Vision]**

- **State serializer**: ViZDoom game variables and label buffer compressed into a compact
  text state — health, ammo, and each visible enemy's bearing and distance.
- **Typed question schema**: a small, fixed battery of questions whose answers compose into
  an action. Mirrors the reference demo's trigger / goal / movement split.
- **Real-time loop**: decision cadence decoupled from engine tick rate via action repeat, so
  model latency degrades responsiveness rather than breaking the game clock.
- **Decision panel UI**: live frame stream beside the current state text, every typed answer
  with its probability, and a rolling latency readout.

## Success Criteria **[REQUIRED]**

1. LAYA completes full Doom episodes end to end with no human input.
2. Decisions sustain the target cadence (~10 Hz) with observed p50 latency reported honestly.
3. A viewer watching the panel can tell *why* the model did what it did on any given tick.
4. The whole thing runs from a clean clone on Apple Silicon with no GPU rental and no API key.

## Principles **[REQUIRED]**

- **Honest about ability.** The demo's claim is latency and calibration, not Doom skill. A
  scripted bot would win. Do not hide that.
- **Show the probabilities.** Calibrated confidence is LAYA's actual selling point, so it
  belongs on screen, not in a log file.
- **The model decides, the code does not.** No scripted fallback quietly playing the game.
  Where heuristics are unavoidable they are visible and labelled as such.
- **Reproducible on one machine.** Local weights, pinned versions, no hosted inference.

## Constraints **[REQUIRED]**

- Apple Silicon (M1 Max, 32GB), macOS 26.2, arm64. MPS rather than CUDA.
- Python >= 3.10 (required by `laya`); ViZDoom ships arm64 wheels for 3.10-3.14.
- LAYA context window is 512 tokens on the English checkpoint, which caps how much game
  state can be described per tick.
- No Hugging Face Space, no deployment target, no hosted inference. Local only.