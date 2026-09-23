---
id: bootstrap-deps-and-decisionclient
level: task
title: "Bootstrap deps and DecisionClient backend contract"
short_code: "LDOOM-T-0001"
created_at: 2026-09-23T02:45:21.933629+00:00
updated_at: 2026-09-23T02:50:58.608745+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/completed"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# Bootstrap deps and DecisionClient backend contract

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Stand up the environment and put one stable seam between this repo and LAYA, so the loop never
cares which backend answers. Pin the `noul` polarity with a test before anything depends on it.

## Acceptance Criteria

## Acceptance Criteria **[REQUIRED]**

- [x] `uv sync` from a clean clone installs ViZDoom 1.3.1 and `laya` on Python 3.12 / arm64.
- [x] `laya-mps` runs locally and `GET /health` returns `{"status":"ready"}`.
- [x] `DecisionClient` protocol defined with `decide(state, questions) -> Decision`.
- [x] `LayaMpsClient` posts to `/v1/decisions?metrics=true` and returns normalised answers.
- [x] `InProcessClient` wraps `laya.load()` and returns the *same* normalised shape.
- [x] Normalisation covers the known divergences (REQ-008): noul confidence present upstream and
      absent in laya-mps; score probabilities as dict upstream and list in laya-mps.
- [x] A test pins `noul` == P(true) against a state where the answer is unambiguous.
- [x] Client records measured wall-clock latency per call, separate from server `request_ms`.
- [x] A missing or unreachable server fails with an actionable message naming `scripts/serve.sh`.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
`laya-mps` is a sibling checkout, not a dependency — talk to it over HTTP and let its URL be
configurable. Use a pooled connection (`httpx.Client`) since we issue ~10 requests/sec to
localhost and per-request TCP setup is pure waste at that cadence.

Normalise to a small dataclass per answer carrying: value, the full probability distribution,
confidence, and question type. The UI needs the distribution, so do not discard it.

### Dependencies
None. This unblocks everything else.

### Risk Considerations
- `laya-mps` pins `laya` at a specific revision; our `pyproject.toml` may resolve a different
  version for `InProcessClient`. They are separate venvs, so this is tolerable, but record the
  versions actually used.
- Discovery measured upstream in-process latency at **58.6 ms on CPU**. If `InProcessClient`
  ends up the only working path, NFR-001 (p50 < 100 ms) still holds, so this is a real fallback
  rather than a nominal one.
- `transformers` 5.17 resolved against `laya`'s `>=4.48` floor. The probe loaded and predicted
  successfully, so 5.x is compatible today; pin it once it works.

## Status Updates **[REQUIRED]**

### 2026-09-22 — complete

`src/laya_doom/client.py` (330 lines) and `tests/test_client.py` (19 passing).

**Measured here** (M1 Max 32GB, macOS 26.2, arm64), server on `--memory full
--question-batch-size 4`, model `convaiinnovations/laya-typed-decisions` rev `f9ab0b2`, fp32/MPS:

| Request | p50 | p95 | min | max |
| --- | ---: | ---: | ---: | ---: |
| 3 questions, batched | **71.5 ms** | 74.0 ms | 69.3 ms | 83.5 ms |
| 1 question | **32.1 ms** | — | 30.5 ms | 847.4 ms |

NFR-001 (p50 < 100 ms) is met with a three-question battery.

**Findings that change later tasks:**

1. `--question-batch-size` defaults to **1** — one forward pass *per question*. Three questions
   at the default would be ~96 ms and miss the budget. Batching them into one pass gives 71.5 ms:
   sublinear against 3x32 ms, but not free. The server must be started with
   `--question-batch-size 4`, and [[LDOOM-T-0006]] must say so, because the default silently
   misses the latency target.
2. **Warmup is mandatory.** First call 686 ms; a cold single-question call hit 847 ms. The loop
   needs warmup dispatches before the first tick — [[LDOOM-T-0004]].
3. **The serialization hypothesis is confirmed.** Identical `turn` question, two state phrasings:

   | State phrasing | Answer | Confidence |
   | --- | --- | ---: |
   | "bearing +6 degrees right" | right — wrong | 0.0115 |
   | "slightly LEFT of your crosshair" | **left — correct** | 0.228 |

   Plain language works where degrees do not. This governs [[LDOOM-T-0002]], and suggests `turn`
   is salvageable rather than cut — [[LDOOM-T-0003]] settles it.
4. `fire` returned 0.402 (no) for an enemy *slightly* left of the crosshair, which is arguably
   correct since it is not lined up yet. Encouraging, not conclusive.

**Decisions:**

- `laya-mps` sits at `~/Desktop/laya-mps` as a sibling checkout, over HTTP. Not vendored.
- Confidence is recomputed locally as normalised negentropy for *every* answer type, matching
  laya-mps's own formula, so `noul` — which laya-mps reports without a confidence — lands on the
  same scale as `choice` and `score`.
- `transformers` 5.17.0 and torch 2.14.0 both work with `laya` 0.3.6. No pinning needed yet.
- `StubClient` got its `delay_ms` knob here rather than in [[LDOOM-T-0004]], since the latch
  tests need it.