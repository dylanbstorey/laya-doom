---
id: deathmatch-scenario-and-lockstep
level: task
title: "deathmatch scenario and lockstep policy harvesting"
short_code: "LDOOM-T-0010"
created_at: 2026-09-23T10:53:40.746821+00:00
updated_at: 2026-09-23T10:53:40.746821+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/todo"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# deathmatch scenario and lockstep policy harvesting

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Test whether LAYA is worth distilling, and if it is, harvest the training set.

## Detailed Design **[REQUIRED]**

**The correction that started this.** Every earlier "LAYA does not beat hand-written rules"
measurement was taken on a **latency-crippled** LAYA. In lockstep — the game does not advance
while the model thinks — the same seed scored **+13 with 14 kills** against real time's **+1 with
2 kills**. I had treated that gap as a reason to distrust lockstep as *dishonest for a demo*,
which it is, and missed that it is exactly right for a **teacher**: harvest the model's best
decisions, not its fastest ones.

**The second thing I underweighted:** a student buys decision *rate*, not just cost. We have
measured that rate matters — skipped slots track directly with worse play. A student running in
well under a millisecond can act **every tic, 35 Hz**, against LAYA's 5–8 Hz. Even at equal
per-decision quality that is 5x the decisions.

**The gate.** A student's ceiling is its teacher, so distillation is only worth doing where the
teacher beats rules someone could write by hand. That is a real test, and on our first two maps
it fails: a scripted policy reading the same state scored 12.4 against LAYA's 8.0 on
`defend_the_center`, and on `deadly_corridor` both lose to walking in a straight line.
`deathmatch` is the honest candidate — 20 buttons, six weapon slots, pickups everywhere, reward
counting only kills — where hand-written rules get awkward.

`bench/gate.py` runs scripted, random and LAYA in lockstep and reports PASS / INCONCLUSIVE /
FAIL against one standard deviation.

**The student, if the gate passes.** Input is the engineered feature vector already implicit in
the state dict, not text — encoding text is the expensive part, so a text student would defeat
the purpose. Output is one head per question, trained on LAYA's **calibrated probability
distributions** as soft targets rather than hard labels, which is the classic setup and carries
strictly more information here because the probabilities are the thing LAYA is good at.

**The caveat worth stating plainly:** a student over engineered features is learning
features → action, and a human can write that mapping — `ScriptedClient` is exactly such a
mapping. The distillation is only interesting if LAYA's mapping is *better* than the one we would
write. That is precisely what the gate measures, which is why it comes first.

## Acceptance Criteria **[REQUIRED]**

- [x] `deathmatch` scenario: 20 buttons, weapon slots, armour, pickups in the state.
- [x] State describes the weapon in hand, its ammunition, and nearby health/ammo/weapon pickups.
- [x] Action mapping applies **every** choice answer, so a weapon switch and a move press
      different buttons in the same tick.
- [x] A deathmatch scripted baseline that is a fair opponent rather than a strawman.
- [x] `bench/gate.py` runs everything in lockstep and reports a verdict against one sd.
- [x] Gate verdict at n=8, with harvesting.
- [x] Feature extractor (37 features) and outcome-tagged harvest, ~4,300 rows.
- [ ] Student and a real-time comparison at full 35 Hz -- see the reframing below.

## Status Updates **[REQUIRED]**

### 2026-09-23 — deathmatch built, gate running

Discovery: reward counts **kills only**; the label buffer is dominated by pickups (RocketBox,
ShellBox, CellPack, Medikit, Stimpack, ClipBox) and weapon drops, not monsters. A random policy
died in ~10 s with zero kills. Weapons are picked up during play (slots 1,2 -> 1,2,3,4).

Built: `DEATHMATCH` scenario (6-tic cadence), weapon/armour/pickup state fields, loadout
narration, `DEATHMATCH_BATTERY` (fire + move + weapon — three questions, affordable because
harvesting is lockstep), `DeathmatchScriptedClient`, and `bench/gate.py`. 150 tests passing.

**First signal, n=2, lockstep** — and it is the opposite of the other two maps:

| policy | score | kills |
| --- | ---: | ---: |
| **laya** | **+7.0** | 3.0 |
| random | +1.5 | 0.5 |
| scripted | +0.5 | 0.5 |

LAYA at 14x the scripted policy. Inconclusive at n=2 (sd 7.1) by the gate's own rule, so an
8-episode run is in flight with `--harvest`.

**Flaw already visible:** LAYA chooses `weapon:pistol` 41% of the time, despite the criterion
saying pistol is for when nothing better has ammunition. Worth fixing before harvesting in
volume — a student trained on that would faithfully learn to hold the worst weapon.


### 2026-09-23 — gate FAILS after six prompt iterations; the question should change

Final, 8 episodes, lockstep, two-question battery with strategy criteria, `scan` and `grab`,
bounded commitments:

| policy | mean score | sd | kills |
| --- | ---: | ---: | ---: |
| scripted | **+5.6** | 3.8 | 2.2 |
| laya | +3.9 | 2.2 | 1.9 |
| random | +2.2 | 3.0 | 1.2 |

**LAYA has converged onto the scripted policy** — scan 39%/33%, aim 39%/41%, hold 23%/19% — and
uses **four of nine** options. `advance`, `grab`, `dodge_left`, `dodge_right` and `retreat` are
all at 0%. It stands, turns and shoots, never walks, and therefore still carries the pistol it
spawned with: across 1436 harvested ticks the player held **one weapon, 100% of the time**.

**Prompt work has hit diminishing returns here.** Six variants across two questions. The two
changes that mattered were both *missing capabilities* (`scan` +3.0, `grab` +1.4 on the scripted
baseline); every wording change was inside the noise. That is the same pattern as
[[LDOOM-T-0008]] and [[LDOOM-T-0009]] and it is now the most robust finding in the project.

**The gate's question is answered, and it is the wrong question.** "Is the teacher smarter than
hand-written rules?" is No, on all three maps. But that was only ever a proxy for whether
distillation is worth doing, and it misses the payoff the user actually identified: a student
buys **decision rate**, not intelligence. LAYA runs at 5–8 Hz and skips 20–65 slots an episode; a
student over 37 features runs in well under a millisecond and can act **every tic, 35 Hz**. We
have measured that rate matters — skipped slots track directly with worse play.

So the live question is no longer "is LAYA better than rules" but **"does the same policy, run
six times more often, play better?"** That is cheap to answer and does not depend on the gate:
~4,300 harvested rows are on disk, tagged with episode outcome, 36% of them from episodes
scoring at or above 5. Filtered cloning on the good episodes, then a real-time comparison of
student-at-35 Hz against LAYA-at-6 Hz and against the scripted policy, answers it directly.

**Recommendation:** stop tuning deathmatch prompts; run that experiment instead.
