# Tuning

`bench/tune.py`, 5 episodes per configuration, fixed seeds, `defend_the_center`.

Episodes run in synchronous fast mode so the game waits for each decision:
no skipped slots, no stale replies, policy quality isolated from latency.
Scores in `defend_the_center` are +1 per kill and -1 for dying, so the spread
between configurations is small in absolute terms and the standard deviation
across episodes is large. Treat anything inside one standard deviation as noise.

## question length

| configuration | mean score | sd | kills | fire rate | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `approach (verbose)` | **+13.00** | 6.16 | 14.0 | 29% | 99 |
| `approach (terse)` | **+5.60** | 4.62 | 6.6 | 24% | 85 |


## Question length: trimming input tokens costs more than it saves

5 episodes each, real time, same seeds. `verbose` is the shipped `TURN_APPROACH`;
`terse` is `TURN_APPROACH_TERSE`, the same five options written short (656 -> 462
chars, 30% smaller).

| configuration | mean score | sd | kills | fire rate | `advance` | `scan` | `hold` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `approach (verbose)` | **+13.00** | 6.16 | 14.0 | 29% | 3% | 23% | 20% |
| `approach (terse)` | +5.60 | 4.62 | 6.6 | 24% | **0%** | 14% | 33% |

A separate interleaved A/B — alternating the two forms request-by-request on identical
states, so ambient machine load falls on both equally — confirms terse really is
faster: p50 **84.2 ms** verbose against **73.6 ms** terse, pooled sd 10.3 ms. So the
10.6 ms saving is real.

It is also a bad trade. Terse scores **less than half**, and the answer distribution
shows where it goes: terse never chooses `advance` at all and scans far less, with
`hold` absorbing the difference. The long criteria are doing work — "so walk forward
to close the distance" and "keep turning to search the room for one" are what make
those options reachable. Compressed to "walk closer" and "keep turning to search", the
model stops picking them and goes back to standing still, which is the same failure the
original `hold` criterion caused.

**Kept verbose.** 194 characters buy 7 points of score for 10 ms.

### Prior stage: does forward movement help?

| configuration | mean score | sd | kills | fire rate |
| --- | ---: | ---: | ---: | ---: |
| `turn=scan (no forward)` | +4.60 | 3.91 | 5.6 | 23% |
| `turn=approach (forward)` | **+13.40** | 5.08 | 14.4 | 30% |

Shipped, despite scoring 85% against `scan`'s 100% on the fixture oracle. The oracle
asserted that advancing is for "aimed but far away" shots; in play its value is that
moving repositions the player and finds enemies, which a single frozen fixture tick
cannot express. Where the offline bench and real episodes disagree, episodes win.
