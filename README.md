# LAYA plays Doom

An open-weights **System 1 decision model** driving Doom's control loop in real time,
on a laptop, for free.

[TypeSafe's Jev demo](https://www.seangoedecke.com/jev-means-structured-output-is-interesting-again/)
showed a non-autoregressive decision model playing Doom at roughly 10 decisions per
second for about $7/hour of hosted inference. [LAYA](https://huggingface.co/convaiinnovations/laya-typed-decisions)
is the same model class with open weights (421M params, Apache 2.0), so the same demo
should run locally for nothing. This is that demo.

Doom runs in [ViZDoom](https://github.com/Farama-Foundation/ViZDoom). Every ~114 ms the
game state is serialized to plain English, sent to LAYA with two typed questions, and the
answers become key presses. The browser shows the frame beside the exact prompt, every
answer with its calibrated probability distribution, and live latency.

**It does not play Doom well.** That is not the claim. The claim is that a 421M model
holds a real-time control loop on consumer hardware, and tells you honestly when it does
not know what to do.

---

## What you need

- **Apple Silicon Mac** (M1 or newer), macOS 14+. The decision server is Metal-based.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- ~4 GB free disk for the model and runtime.

No GPU rental, no API key, no Hugging Face token.

## Setup

Two repos, side by side. This one, and the model server.

```bash
# 1. the decision server (separate repo, MIT)
git clone https://github.com/afshinm/laya-mps.git
cd laya-mps
./scripts/serve.sh --memory full --question-batch-size 4
```

Leave that running. First start downloads ~843 MB and takes a few minutes; later starts
are offline. Wait until it prints `Application startup complete`, then check it:

```bash
curl -s http://127.0.0.1:8000/health     # {"status":"ready","busy":false}
```

> **`--question-batch-size 4` matters.** The default is `1`, which runs one forward pass
> *per question* and misses the frame budget. Batching the battery into a single pass took
> measured p50 from ~96 ms to ~62 ms here.

```bash
# 2. this repo, in a second terminal
git clone https://github.com/dylanbstorey/laya-doom.git
cd laya-doom
uv sync
./run.sh
```

Open **<http://127.0.0.1:8100>** and press **Start**.

The first few seconds are warmup — a cold decision took 686 ms here, so the loop pays that
cost twice before the episode starts rather than during it.

## What you are looking at

**Left:** the Doom viewport at 320×240, streaming at Doom's own 35 fps, with the key row
lighting up as LAYA presses `turn left` / `turn right` / `attack`.

**Right:** the panel that is actually the demo.

- **What the model was asked** — the verbatim state text for this tick. Nothing is hidden.
- **What it answered** — each typed answer with its *full* probability distribution, not
  just the winning label. `fire` is a `noul` (a probability that a statement is true);
  `turn` is a 4-way `choice`.
- Any answer whose confidence falls below 0.15 gets a **dashed amber border** and says so.
  That is the model reporting that it is guessing, which is the thing this model class is
  actually selling.
- **Latency** — last / p50 / p95 and the share of the frame budget used. The sparkline
  turns red on any decision that overran the interval.

The answers panel only refreshes when a reply **lands** (~8.75/s) while the frame updates
~35/s. Between replies the latch is coasting on the last decision, which is why play looks
slightly steppy. That is deliberate — see *the latch* below.

**Switch the dropdown** to `scripted baseline` or `random baseline`. Both read the same
state text, at the same cadence, through the same latch, with the same four turn options.
Only the decision procedure differs.

## Watching it from the terminal instead

```bash
uv run python play.py --policy laya -n 3       # LAYA, three episodes
uv run python play.py --policy all -n 4       # LAYA vs both baselines
uv run python play.py --window                # native Doom window
uv run python play.py --help
```

## How it works

```
laya-mps server            laya-doom (this repo)              browser
127.0.0.1:8000             127.0.0.1:8100
     ^                          |
     |  POST /v1/decisions      |  ViZDoom headless, in-process
     |  <= 1 in flight          |    state  -> state.py   -> plain English
     +--------------------------+    answers -> actions.py -> button vector
                                |
                                +--> WebSocket: JPEG frame + decision record
```

| file | what it does |
| --- | --- |
| `src/laya_doom/state.py` | ViZDoom state → the English the model reads |
| `src/laya_doom/questions.py` | the shipped question battery, and the candidates it beat |
| `src/laya_doom/client.py` | one seam over two backends, normalising their answer shapes |
| `src/laya_doom/loop.py` | cadence, latch, generation guard, real-time pacing |
| `src/laya_doom/actions.py` | answers → key presses. Deliberately dumb |
| `src/laya_doom/baselines.py` | scripted and random policies, as `DecisionClient`s |
| `src/laya_doom/server.py` | FastAPI + WebSocket |
| `bench/` | fixtures, question-schema scoring, tuning sweeps |

### Where the line is

**Python computes the observation. The model chooses the action.**

`state.py` works out bearing, distance, and whether the crosshair is on an enemy, then says
so in words — the same job the reference Pong demo does when it computes "above / below /
aligned" in JavaScript. What to *do* about it is entirely the model's. No scripted fallback
quietly plays the game, and `actions.py` only thresholds and looks up.

The one seam worth naming: when the model answers `scan`, the code renders that as a
consistent turn direction. Choosing to search is the model's; sweeping one way rather than
oscillating is mechanical execution.

### The state text is the whole ball game

The same `turn` question, two ways of describing an identical situation:

| state phrasing | answer | confidence |
| --- | --- | ---: |
| `"bearing +6 degrees right"` | wrong | **0.0115** |
| `"slightly LEFT of your crosshair"` | **correct** | 0.228 |

LAYA was trained on support tickets, invoices and security incidents. It is not a spatial
reasoner and will not do trigonometry, but it handles a plain-English spatial relation well.
Across the fixture set, the best `turn` phrasing scored **100%** on English states and
**57%** on degrees-and-coordinates states. That gap is the only reason `state.py` exists.

### The latch

Ported from the reference demo. A reply applies for exactly one interval, then the action
decays to neutral. At most one request is ever in flight; a slot that opens while a request
is out is **skipped, not queued**. Replies are tagged with a generation, so restarting an
episode discards anything still in the air.

The model is called on a **worker thread while the game keeps advancing**. Blocking on each
decision would have been easier and dishonest — with the world paused while the model
thinks, latency costs nothing. Measured on one seed, the paused version scored +13 with 14
kills against real time's +1 with 2 kills. That gap *is* the cost of latency, and the demo
should pay it.

### Cadence is in tics, not milliseconds

Doom's clock is 35 tics/sec, so 10 Hz is 3.5 tics and is not expressible. An interval that
is not a whole number of tics expires a fraction before the loop next looks at the world,
and every action decays after a single tic — play came out far more sluggish than the
latency warranted. The interval snaps to whole tics; the default is **4 tics = 114.3 ms =
8.75 decisions/sec**.

## Measured here

M1 Max, 32 GB, macOS 26.2, `laya-typed-decisions` fp32 on MPS, `--memory full
--question-batch-size 4`. **Not** the M5 Pro figures from the `laya-mps` README.

| request | p50 | p95 | max |
| --- | ---: | ---: | ---: |
| 2-question battery, enemy visible | 80.0 ms | — | 97.5 ms |
| 2-question battery, empty view | 61.2 ms | — | 69.6 ms |
| single question | 32.1 ms | — | — |
| cold first call | 686 ms | — | 847 ms |

Against a 114.3 ms interval, p50 uses ~54–70% of the frame budget.

### Question battery

Two questions, chosen by `bench/score.py` over nine candidates against 40 labelled states.
Full numbers in [`bench/results.md`](bench/results.md).

| question | type | balanced accuracy |
| --- | --- | ---: |
| `fire` | `noul` | **97%** |
| `turn` | `choice` (left / right / hold / scan) | **100%** |

`fire=True` occurs in only 12% of states, so an "always no" answer scores 88% raw accuracy.
Balanced accuracy is the honest measure, and the three `fire` phrasings all had 100% recall
while differing wildly in specificity — 94% for the shipped one against 43% and 37% for two
that read more naturally and held the trigger down.

A third question, `threat` (a `score` rating danger), was **cut**. Across three phrasings
and a paired health sweep holding geometry fixed, it moved at most +0.17 on a 0–2 scale as
health fell from 100 to 5. It tracked danger far too weakly to show anyone, and it was
costing a third of the frame budget.

### It scans now

The first battery shipped `hold` meaning *"centred in the crosshair, **or** no enemy is in
sight"*, which instructed the model to sit still whenever its view was empty. It obediently
held 88% of the time and waited for enemies to wander past. Giving searching its own `scan`
option — and narrowing `hold` to "already aimed" — is the single largest change in the repo.
The model picks `scan` correctly on 100% of empty-view fixtures.

### Honest scoreboard

`defend_the_center`: +1 per kill, −1 for dying. Variance across episodes is large, so treat
small gaps as noise.

4 episodes per policy, same seeds, all three with the same four turn options:

| policy | mean score | kills | decisions/s | p50 | skipped slots |
| --- | ---: | ---: | ---: | ---: | ---: |
| **laya** | **+2.8** | 3.8 | 6.9 | 76.8 ms | **20** |
| scripted | +9.0 | 10.0 | 8.7 | — | 0 |
| random | +1.5 | 2.5 | 8.8 | — | 0 |

LAYA beats random and reaches about **a third** of the scripted reference policy — the same
policy `bench/score.py` scores its questions against, and effectively the ceiling this state
representation allows.

Two things are worth reading off that table.

**The `scan` fix was worth ~9× to the model.** Before it, LAYA scored +0.3 with 1.3 kills and
*lost* to random. One question-design change — giving searching its own option instead of
folding it into `hold` — moved it to +2.8. The scripted policy gained even more, from +0.3 to
+9.0, which is why it looks so dominant now: it had been equally crippled by being told to
stand still.

**LAYA makes 6.9 decisions/sec where the baselines make 8.7.** It skipped 20 slots per
episode because p95 latency (99.8 ms) crowds the 114.3 ms interval, so roughly a fifth of its
opportunities to act are spent waiting on inference. The baselines answer instantly and never
skip. That missing 20% of decisions is the price of putting a real model in the loop, and it
is visible in the score rather than hidden.

## Running the tests

```bash
uv run pytest -q          # 111 tests, no model or Doom process needed
```

They concentrate on what fails *silently*: the sign of a bearing, the polarity of a `noul`,
a stale reply steering a fresh episode, whether the action ever reaches the game at all.
That last one was a real bug — `advance_action` takes no buttons, so omitting `set_action`
advanced the world with nothing pressed, and every policy looked incompetent while nothing
was ever pressed.

## Credits

- [LAYA](https://huggingface.co/convaiinnovations/laya-typed-decisions) — weights, Apache 2.0, by Convai Innovations
- [laya-mps](https://github.com/afshinm/laya-mps) — the Apple Silicon decision server, MIT. Its Pong demo is where this loop's structure comes from
- [ViZDoom](https://github.com/Farama-Foundation/ViZDoom) — Doom as a research environment
- TypeSafe's Jev × Doom demo — the prior art this reimplements with open weights

Planning docs, including every finding and reversal along the way, are in
[`.metis/`](.metis/).
