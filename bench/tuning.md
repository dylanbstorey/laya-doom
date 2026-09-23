# Tuning

`bench/tune.py`, 5 episodes per configuration, fixed seeds, `defend_the_center`.

Episodes run in synchronous fast mode so the game waits for each decision:
no skipped slots, no stale replies, policy quality isolated from latency.
Scores in `defend_the_center` are +1 per kill and -1 for dying, so the spread
between configurations is small in absolute terms and the standard deviation
across episodes is large. Treat anything inside one standard deviation as noise.

## advance

| configuration | mean score | sd | kills | fire rate | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `turn=scan (no forward)` | **+4.60** | 3.91 | 5.6 | 23% | 75 |
| `turn=approach (forward)` | **+13.40** | 5.08 | 14.4 | 30% | 101 |

