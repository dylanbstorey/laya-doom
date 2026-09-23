# deadly_corridor

`bench/corridor.py`, 4 episodes per configuration, fixed seeds, real time.

This map has **no fixture oracle**. The right action depends on the whole trajectory —
whether stopping to shoot costs more distance than it saves — which a single frozen
tick cannot express. Configurations are judged only by what they score.

## The bar

Reward is distance travelled toward a vest 1312 units away, and dying costs 100. So a
policy that walks blindly into the corridor and dies partway still banks a few hundred
points. **That is the bar, not zero.**

| policy | mean score | sd | reached | best | p50 | skipped/ep |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **forward** (blind) | **+271.6** | 124.0 | 28% | 39% | — | 0 |
| laya / `blocking` | +107.2 | 118.6 | 16% | 29% | 117 ms | 97 |
| scripted | +83.8 | 191.5 | 19% | 32% | — | 0 |
| laya / `threat` | +60.6 | 147.0 | 12% | 26% | 126 ms | 68 |
| laya / `binary` | +8.1 | 42.9 | 8% | 13% | 86 ms | 1 |
| random | −104.4 | 9.0 | 2% | 3% | — | 0 |
| laya / `lean` | −116.0 | 0.0 | 0% | 0% | 105 ms | 4 |

## What it says

**Walking forward blindly beats every policy here, including the scripted reference.**
That is the honest headline, and it is not a LAYA result: a hand-written policy with
perfect access to the same state also loses to walking in a straight line. The reward
pays for distance, and every decision to stop and aim costs distance. The framing
"aim at what you see, advance when clear" is simply wrong for this map.

**LAYA clearly beats random** (+107 against −104), so the decisions are doing something.
It does not clearly beat, or lose to, the scripted policy.

**The differences among LAYA variants are inside the noise.** With n=4 and standard
deviations of 119–147, `blocking` (+107) and `threat` (+61) are indistinguishable. Only
two statements survive: `lean` is genuinely broken, and `forward`'s margin over
everything is large enough to take seriously while still wanting more episodes.

## Where the analysis was wrong

The first corridor question made `advance` read *"No enemy is blocking the way"*. The
corridor always has enemies in view, so the option was unreachable by construction, and
the model obeyed exactly: `advance` 0%, progress 0%, score −116.

That diagnosis was right about the mechanism and **wrong about the fix**. Rewriting the
criteria around threat rather than visibility *reduced* advancing from 23% to 7% and
halved the score. The variant predicted to be broken scored best of the four.

**Trimming the action space backfired badly.** `dodge_left`, `dodge_right` and `retreat`
were chosen zero times in early runs, so `lean` dropped them — and `lean` scored −116
with a standard deviation of **0.0**, choosing aim 97% of the time and advancing never,
in every single episode. Removing unused options changed the answers to the ones that
remained. This is the same lesson as `TURN_APPROACH_TERSE` in `tuning.md`: the option
set is not a menu the model picks from independently, it is context that shapes every
answer.

**`binary` bought latency and spent it on nothing.** Two options ran at p50 86 ms with
1 skipped slot per episode, against `threat`'s 126 ms and 68 skips — by far the
healthiest loop in the table. It then chose `hold` 64% of the time and stood still.
More decisions per second is worthless if the decisions are to do nothing.

## Latency

The corridor is latency-bound in a way `defend_the_center` is not: a seven-option
question plus a longer state text (608–724 chars against 400–550) runs p50 117–126 ms
against a 143 ms interval, skipping 68–97 slots per episode. The cheaper questions fix
the loop health and lose on score anyway.
