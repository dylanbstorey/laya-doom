---
id: laya-doom-live-demo
level: initiative
title: "LAYA Doom live demo"
short_code: "LDOOM-I-0001"
created_at: 2026-09-23T02:41:12.963654+00:00
updated_at: 2026-09-23T02:49:35.947717+00:00
parent: LDOOM-V-0001
blocked_by: []
archived: false

tags:
  - "#initiative"
  - "#phase/active"


exit_criteria_met: false
estimated_complexity: M
initiative_id: laya-doom-live-demo
---

# LAYA Doom live demo Initiative

## Context **[REQUIRED]**

TypeSafe's Jev demo put a non-autoregressive System 1 model inside Doom's control loop at
~10 decisions/sec and ~$7/hour of hosted inference. LAYA is the open-weights equivalent.
`afshinm/laya-mps` (MIT) already wraps the `laya-typed-decisions` checkpoint in an
MPS-optimised local HTTP server and ships a **Pong** demo built on exactly the loop we need.
This initiative extends that precedent from Pong to Doom.

Discovery is done. Measured on this machine (M1 Max, 32GB, macOS 26.2, arm64):

- ViZDoom 1.3.1 installs from an arm64 wheel, runs headless, and exposes per-object labels
  with world position and screen bounding box. No compilation needed.
- Upstream in-process `laya` 0.3.6 loads and answers 3 questions at **p50 58.6 ms** (CPU).
- `laya-mps` reports **~32 ms** median on MPS and exposes `POST /v1/decisions`.

A throwaway probe also exposed the central risk. Given the state text
`"marine, bearing +6 degrees right, distance 682, in crosshair"`:

| Question | Answer | Confidence |
| --- | --- | --- |
| `shoot` (noul) | 0.897 — correct | 0.897 |
| `turn` (choice) | "right" | **0.0115** — near-uniform, no signal |

LAYA is a decision model trained on support tickets, invoices and security incidents. It is
not a spatial reasoner and will not do trigonometry. Its calibration correctly reported that
it did not know. The demo therefore lives or dies on **state phrasing**, which makes question
design an empirical task with a measurable target, not a thing to guess at once and ship.

## Goals & Non-Goals **[REQUIRED]**

**Goals:**
- LAYA plays unattended Doom episodes end to end via `laya-mps` at a ~10 Hz decision cadence.
- A browser panel shows the live frame, the exact state text sent, every typed answer with its
  calibrated probability, and rolling latency.
- Question schemas are chosen against a labelled fixture set, not vibes.
- Runs from a clean clone on Apple Silicon with no API key and no hosted inference.

**Non-Goals:**
- Playing Doom *well*. A scripted bot wins; NFR-004 keeps us honest about that.
- Hugging Face Space, deployment, or any hosted target. Local only; GitHub is the ceiling.
- Training, fine-tuning or modifying LAYA weights.
- Vendoring or forking `laya-mps`. It is a sibling process we talk to over HTTP.

## Requirements

### System Requirements
- **Functional Requirements**
  - REQ-001: Serialize ViZDoom state to a compact dict — health, ammo, and per visible enemy a
    plain-language bearing/distance description, mirroring the pong demo's `observation` idiom.
  - REQ-002: Exclude the `DoomPlayer` self-label from the enemy list.
  - REQ-003: Map typed answers to ViZDoom button vectors.
  - REQ-004: Latch each decision for exactly one control interval, then decay to neutral, so a
    slow reply degrades responsiveness instead of desynchronising the game clock.
  - REQ-005: Discard replies from a superseded episode or generation.
  - REQ-006: Stream frames and decision records to a browser over WebSocket.
  - REQ-007: Display each answer's probability and confidence, including low-confidence ones.
  - REQ-008: Normalise the two backends' differing answer shapes behind one client interface
    (`laya-mps` returns `{noul}` and a probability *list*; upstream returns `confidence` on
    noul and a probability *dict*).
  - REQ-009: Offline fixture harness scoring a question schema against labelled states.
- **Non-Functional Requirements**
  - NFR-001: Decision p50 under 100 ms so the 10 Hz cadence is real, measured and reported.
  - NFR-002: At most one in-flight request; the server enforces `max_active_requests: 1`.
  - NFR-003: Keep questions few (<= 4). Multiple questions can span multiple forward passes,
    and every extra pass eats the frame budget.
  - NFR-004: Report episode score next to a scripted baseline, so "LAYA plays badly" is a
    measured statement rather than a disclaimer.
  - NFR-005: State text must fit the 1024-token typed-decisions context; cap the enemy list.

## Use Cases **[CONDITIONAL: User-Facing Initiative]**

### Use Case 1: Watch LAYA play
- **Actor**: the author
- **Scenario**: start `laya-mps`, run `./run.sh`, open the browser, press Start.
- **Expected Outcome**: Doom runs unattended; each tick the panel shows the state text, the
  chosen action, its probability and the latency.

### Use Case 2: Inspect a bad decision
- **Actor**: the author
- **Scenario**: LAYA fires at nothing. He pauses and reads the last decision record.
- **Expected Outcome**: the state text and probability distribution explain it — either the
  state was misleading or the model was confidently wrong, and the panel distinguishes these.

## Architecture **[CONDITIONAL: Technically Complex Initiative]**

### Overview
Three processes, one direction of data flow:

```
laya-mps server            laya-doom app                     browser
(sibling process)          (this repo)                       (static page)
127.0.0.1:8000             127.0.0.1:8100
     ^                          |
     |  POST /v1/decisions      |  ViZDoom (headless, in-process)
     |  <= 1 in flight          |    state -> serializer -> dict
     +--------------------------+    answers -> action mapper -> buttons
                                |
                                +--> WebSocket: JPEG frame + decision record
```

### Component Diagrams
- `state.py` — ViZDoom `GameState` -> state dict (REQ-001, REQ-002, NFR-005)
- `questions.py` — the question battery, versioned so fixtures can score revisions
- `client.py` — `DecisionClient` protocol; `LayaMpsClient` (HTTP) and `InProcessClient`
  (upstream `laya.load`) both normalise to one answer shape (REQ-008)
- `loop.py` — cadence, latch, generation guard, episode management (REQ-004, REQ-005)
- `actions.py` — answers -> button vector (REQ-003)
- `server.py` — FastAPI + WebSocket (REQ-006)
- `static/` — frame canvas + decision panel (REQ-007)
- `bench/` — labelled fixtures and schema scoring (REQ-009)

### Sequence Diagrams
Per control interval: loop reads `GameState` -> `state.py` builds dict -> `client.py` POSTs ->
answers normalised -> `actions.py` produces buttons -> `game.make_action(buttons, tics)` ->
frame + record pushed to browser. If a reply is still in flight when the next slot opens, the
slot is skipped rather than queued (NFR-002).

## Detailed Design **[REQUIRED]**

**Scenario.** `defend_the_center` is the primary target: the player is fixed in place with only
`TURN_LEFT`, `TURN_RIGHT`, `ATTACK`, and enemies close in from all sides. It isolates reactive
aim-and-fire with no navigation, which is the narrowest honest test of a System 1 loop.
`deadly_corridor` is a stretch goal once navigation questions exist.

**Geometry belongs in Python, decisions belong to LAYA.** The pong demo computes
"above / below / aligned" in JS and asks only *what to do about it*; the probe proves LAYA will
not convert "bearing +6 degrees" into a turn direction. So `state.py` computes bearing from the
label bounding-box centre against the screen centre and emits words — "the nearest enemy is
slightly LEFT of your crosshair" — plus raw numbers alongside. This is the line the vision's
"the model decides, the code does not" principle draws: **code computes observations, the model
chooses actions.** Any heuristic that crosses into choosing is a bug and gets labelled in the UI.

**Bearing from screen space, not world space.** Screen bbox centre already folds in FOV and
player angle, and is robust to the scenario's odd `POSITION_X/Y` reporting (both read 0.0 in the
probe). World coordinates are used only for distance.

**The latch is load-bearing.** Copied deliberately from `decisions.mjs`: apply a reply for one
100 ms interval on arrival, then neutral. Without it, a 200 ms reply either stacks up or freezes
the game. With it, latency shows up as sluggishness, which is the honest failure mode.

**Question battery** (<= 4, per NFR-003), to be confirmed by fixtures rather than assumed:
`fire` (noul, "an enemy is lined up right now"), `turn` (choice: left/right/hold),
`threat` (score). Wording iterates in `bench/`; whatever the fixtures pick is what ships.

**noul semantics.** `laya-mps` reverses Laya's native `[false, true]` ordering, so the `noul`
field is **P(true)**. Encode this once in `client.py` with a test pinning it, because getting it
backwards inverts the trigger and would be maddening to debug from gameplay alone.

## Testing Strategy **[CONDITIONAL: Separate Testing Initiative]**

### Unit Testing
- **Strategy**: pure functions get real tests — serializer against recorded `GameState`
  fixtures, action mapper against synthetic answers, latch/generation logic against a fake
  clock, noul polarity pinned explicitly.
- **Tools**: pytest. No coverage target; this is a demo, and tests exist where they catch
  silent wrongness rather than to hit a number.

### Integration Testing
- **Strategy**: a headless episode with a stub client (fixed answers) proving the loop runs
  without a model; then a short live episode against `laya-mps`.
- **Test Environment**: local only.

### Test Selection
Test what fails silently: bearing sign, noul polarity, stale-reply handling, answer-shape
normalisation. Do not test ViZDoom or LAYA themselves.

## Alternatives Considered **[REQUIRED]**

- **In-process upstream `laya` instead of `laya-mps`** — measured 58.6 ms vs ~32 ms, and puts
  torch in the game loop's process. Kept as a fallback behind `DecisionClient` so a broken
  server never blocks progress, but not the default.
- **GameNGen / neural world models (Oasis, DIAMOND)** — these *generate* Doom. LAYA cannot;
  it emits typed decisions, never pixels or text. Wrong model class entirely; noted because
  "model plays Doom" invites the confusion.
- **An LLM with constrained decoding** — the alternative Sean Goedecke describes (prefill, one
  constrained token). Faster than naive structured output but still autoregressive, and it
  would make the demo about prompt engineering rather than about the model class.
- **Gymnasium/`vizdoom.gymnasium_wrapper`** — an RL-shaped abstraction we would spend the whole
  time fighting, since we need raw labels and a custom cadence, not `step()`/`reset()`.
- **Reading enemy bearing from the depth buffer** — richer, but the label buffer already gives
  exact per-object boxes. Unnecessary complexity.

## Implementation Plan **[REQUIRED]**

Vertical slices, each independently runnable:

1. **Bootstrap + backend contract** — deps pinned, `laya-mps` running, `DecisionClient` with
   both implementations, noul polarity pinned by test.
2. **State serializer** — `GameState` -> state dict, with recorded fixtures.
3. **Question schema bench** — labelled fixtures, score candidate schemas, pick the battery.
4. **Headless loop** — cadence, latch, generation guard, action mapping; plays a full episode
   with the stub and then live. Baseline score recorded here (NFR-004).
5. **Browser UI** — WebSocket frame stream, decision panel with probabilities and latency.
6. **README + capture** — setup instructions, honest numbers, a recorded clip.

Slices 1-4 are the demo; 5 is what makes it worth showing; 6 is what makes it shareable.