# deathmatch prompt eval

`bench/prompts.py` and `bench/gate.py`, lockstep, bounded commitments active.

## What moved the score

| change | before | after |
| --- | ---: | ---: |
| adding `scan` (scripted baseline) | +1.2 | **+4.2** |
| adding `grab` (scripted baseline) | +4.2 | **+5.6** |
| strategy ordering in criteria (LAYA, 4 ep) | +5.25 | +5.75 |
| weapon question, `blind` vs `inventory` | +5.25 | +5.25 (**identical**) |

## The gate

8 episodes each, two-question battery, strategy criteria, `scan` + `grab`:

| policy | mean score | sd | kills | p50 |
| --- | ---: | ---: | ---: | ---: |
| scripted | **+5.6** | 3.8 | 2.2 | — |
| laya | +3.9 | 2.2 | 1.9 | 127 ms |
| random | +2.2 | 3.0 | 1.2 | — |

**FAIL.** LAYA does not beat hand-written rules on deathmatch either, so by the
gate's rule there is nothing to distil that is not already available for free.

## Why, in one table

Move answers actually used, LAYA against the scripted policy:

| option | laya | scripted |
| --- | ---: | ---: |
| `scan` | 39% | 33% |
| `aim_left` / `aim_right` | 39% | 41% |
| `hold` | 23% | 19% |
| `retreat` | 0% | 7% |
| `advance`, `grab`, `dodge_left`, `dodge_right` | **0%** | 0% |

LAYA has converged onto the scripted policy, and uses **four of nine** available
options. It stands, turns and shoots. It never walks, which is why it still holds
the pistol it spawned with: measured across 1436 harvested ticks, the player
carried **one weapon, 100% of the time**. Offering `grab` did not change that —
the option exists and is never chosen.

## Three constraints found the hard way

**Missing capabilities dominate everything else.** `scan` was worth +3.0 to the
scripted baseline, `grab` another +1.4. Both are options that did not previously
exist. No wording change came close to either.

**Instructions are capped at 192 tokens.** laya-mps rejects a request with a 422
rather than silently truncating the question head. The first strategy variant was
refused outright. Criteria are not capped, and criteria-led already beat
instruction-led on the `turn` bench (98% vs 85%), so strategy belongs in the
options as `FIRST:` / `SECOND:` / `LAST:` labels.

**The whole formatted prompt is capped at 512 tokens.** Nine options plus a
deathmatch state ran to ~502 and tipped over on long states. Cutting the loadout
prose — dead weight once the weapon question was cut, since the player never
carries a second weapon — brought it to ~468.

## The weapon question was cut

Like `threat` before it. `blind` and `inventory` scored *identically* — same
score, same sd, same kills, same move distribution — while answering completely
differently (`pistol` 39% against `keep` 40%). Every weapon answer was a no-op
because there was never a second weapon to switch to. It cost ~12 ms a decision
(197 ms against 185 ms) and changed nothing.
