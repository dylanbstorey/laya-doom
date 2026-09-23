"""The typed questions LAYA answers, and the candidates they were chosen over.

Discovery produced one question that worked first try (`fire`, 0.897) and one
that collapsed to noise (`turn`, confidence 0.0115), so the shipped battery is
picked by `bench/score.py` against fixtures rather than by taste.

Kept to three questions. `--question-batch-size` batches them into a single
forward pass, measured at p50 71.5 ms for three against 32 ms for one; each
extra question eats the 100 ms frame budget (NFR-003).

Note the two backends spell a score question's levels differently -- `levels`
here for laya-mps, translated to `criteria` by `InProcessClient`.
"""

from __future__ import annotations

# --- fire ------------------------------------------------------------------
# Phrased as a statement rather than a question: `noul` estimates whether a
# statement is true, which is what the checkpoint was trained to do.

FIRE_STATEMENT = {
    "type": "noul",
    "instructions": (
        "An enemy is lined up with the player's crosshair right now, so firing the weapon "
        "would hit an enemy."
    ),
}

FIRE_QUESTION = {
    "type": "noul",
    "instructions": "The player should pull the trigger right now.",
}

FIRE_WASTE = {
    "type": "noul",
    "instructions": (
        "Firing right now would hit an enemy rather than waste a bullet on empty space."
    ),
}

# --- turn ------------------------------------------------------------------
# The question discovery showed failing. Three phrasings compete.

TURN_DIRECTIVE = {
    "type": "choice",
    "instructions": (
        "The player is aiming at a fixed crosshair and can turn left or right to move it. "
        "Choose left if the enemy is to the left of the crosshair, right if the enemy is to "
        "the right of the crosshair, and hold if the enemy is already centred in the "
        "crosshair or no enemy is visible."
    ),
    "criteria": {
        "left": "Turn left, because the enemy is to the left of the crosshair",
        "right": "Turn right, because the enemy is to the right of the crosshair",
        "hold": "Do not turn, because the crosshair is already on the enemy or there is no enemy",
    },
}

TURN_TERSE = {
    "type": "choice",
    "instructions": "Which way should the player turn to put the crosshair onto the nearest enemy?",
    "criteria": {"left": "Turn left", "right": "Turn right", "hold": "Do not turn"},
}

TURN_CRITERIA_LED = {
    "type": "choice",
    "instructions": "Turn the player's aim toward the nearest enemy.",
    "criteria": {
        "left": "The nearest enemy is to the left of the crosshair",
        "right": "The nearest enemy is to the right of the crosshair",
        "hold": "The nearest enemy is centred in the crosshair, or no enemy is in sight",
    },
}

# --- turn, with searching as an option -------------------------------------
# The first battery shipped `hold` meaning "centred in the crosshair, OR no enemy
# is in sight", which instructed the model to sit still whenever its view was
# empty. It obediently held 88% of the time and waited for enemies to wander into
# the view cone. These variants give searching its own option so the model can
# choose it; `hold` now means only "already aimed, do not spoil the shot".

TURN_SCAN = {
    "type": "choice",
    "instructions": "Aim at an enemy, or search for one if none is visible.",
    "criteria": {
        "left": "An enemy is visible and is to the left of the crosshair",
        "right": "An enemy is visible and is to the right of the crosshair",
        "hold": "An enemy is centred in the crosshair, so stop turning and shoot it",
        "scan": "No enemy is visible, so keep turning to search the room for one",
    },
}

TURN_SCAN_URGENT = {
    "type": "choice",
    "instructions": (
        "Aim at an enemy, or search for one if none is visible. Standing still with an empty "
        "view means enemies approach unseen, so searching is better than waiting."
    ),
    "criteria": {
        "left": "An enemy is visible and is to the left of the crosshair",
        "right": "An enemy is visible and is to the right of the crosshair",
        "hold": "An enemy is centred in the crosshair, so stop turning and shoot it",
        "scan": "Nothing is visible, so sweep the view around to find an enemy",
    },
}

# --- turn, with closing distance as an option ------------------------------
# Adding `advance` to the existing choice rather than asking a third question:
# p95 latency is already 99.8 ms against a 114.3 ms interval and ~20 slots per
# episode are skipped, so another forward pass would cost more decisions than the
# extra action buys.

TURN_APPROACH = {
    "type": "choice",
    "instructions": "Aim at an enemy, close the distance on it, or search for one if none is visible.",
    "criteria": {
        "left": "An enemy is visible and is to the left of the crosshair",
        "right": "An enemy is visible and is to the right of the crosshair",
        "hold": "An enemy is centred in the crosshair and is close enough to shoot, so stop moving and shoot it",
        "advance": "An enemy is centred in the crosshair but is far away, so walk forward to close the distance",
        "scan": "No enemy is visible, so keep turning to search the room for one",
    },
}

# The same five options, written short -- and NOT shipped. Kept because the result is
# worth preserving.
#
# Trimming looked free. Question text is re-tokenised every tick, and an interleaved
# A/B (alternating forms request-by-request on identical states, so ambient machine
# load falls on both equally) measured a 30% smaller payload buying a real 10.6 ms:
# p50 84.2 ms verbose against 73.6 ms terse, pooled sd 10.3 ms.
#
# It is not free. Over 5 episodes each, terse scored **+5.6 against verbose's +13.0**
# -- less than half, a 7.4 point gap against standard deviations of 4.6 and 6.2. The
# answer distribution says why: terse picked `advance` **0%** of the time against 3%,
# and `scan` 14% against 23%, with `hold` absorbing the difference (33% vs 20%). The
# longer criteria are not padding. Phrases like "so walk forward to close the
# distance" and "keep turning to search the room for one" are what make those options
# reachable at all; compressed to "walk closer" and "keep turning to search", the
# model stops choosing them and reverts to standing still.
#
# 194 characters buy 7 points of score for 10 ms. That is the trade, and it is not
# close.

TURN_APPROACH_TERSE = {
    "type": "choice",
    "instructions": "Aim at an enemy, close on it, or search for one.",
    "criteria": {
        "left": "An enemy is left of the crosshair",
        "right": "An enemy is right of the crosshair",
        "hold": "An enemy is centred and close enough to shoot",
        "advance": "An enemy is centred but far away; walk closer",
        "scan": "No enemy visible; keep turning to search",
    },
}

# --- threat ----------------------------------------------------------------

THREAT = {
    "type": "score",
    "instructions": "How much immediate danger is the player in?",
    "levels": ["safe", "under threat", "about to die"],
}

THREAT_HEALTH = {
    "type": "score",
    "instructions": (
        "Rate the player's condition. The player has a health value out of 100 and is being "
        "attacked by enemies. Low health means the player is close to dying."
    ),
    "levels": ["unhurt and safe", "wounded", "close to death"],
}

THREAT_SURVIVAL = {
    "type": "score",
    "instructions": "How likely is the player to die in the next few seconds?",
    "levels": ["very unlikely", "possible", "very likely"],
}

# The shipped battery, chosen by bench/score.py and bench/threat.py. See
# bench/results.md for the numbers; change these only with a bench run behind it.
#
# Two questions, not three. `threat` was cut: across three phrasings and a paired
# health sweep holding geometry fixed, the score moved at most +0.17 on a 0-2
# scale as health fell from 100 to 5. It tracked health directionally but far too
# weakly to show anyone, and it was costing a third of the frame budget.
#
# The winners are not the phrasings that looked most natural:
#   fire -> FIRE_QUESTION ("should pull the trigger"), balanced accuracy 97%,
#           against 71% and 69% for the two statement-shaped phrasings, which
#           fired almost constantly (specificity 43% and 37%).
#   turn -> TURN_APPROACH, which adds `scan` (search when nothing is visible) and
#           `advance` (close on a distant target) to the aim options.
#
# `turn` is the one place where the bench oracle and actual play disagree, and play
# wins. TURN_APPROACH scores 85% against TURN_SCAN's 100% on the fixture oracle, yet
# scores roughly 3x better in real episodes (+14.8 against +4.6 mean over 5). The
# oracle asserted that advancing is for "aimed but far away" shots; in play its value
# is that moving repositions the player and finds enemies, which the fixtures --
# single frozen ticks -- cannot express. The oracle was measuring the wrong thing, so
# it is reported rather than obeyed.
BATTERY: dict[str, dict] = {
    "fire": FIRE_QUESTION,
    "turn": TURN_APPROACH,
}

# Candidates the bench compares. Keys name the variant in the results table.
FIRE_VARIANTS = {
    "statement": FIRE_STATEMENT,
    "question": FIRE_QUESTION,
    "waste": FIRE_WASTE,
}

TURN_VARIANTS = {
    "directive": TURN_DIRECTIVE,
    "terse": TURN_TERSE,
    "criteria_led": TURN_CRITERIA_LED,
    "scan": TURN_SCAN,
    "scan_urgent": TURN_SCAN_URGENT,
    "approach": TURN_APPROACH,
    "approach_terse": TURN_APPROACH_TERSE,
}

THREAT_VARIANTS = {
    "danger": THREAT,
    "health": THREAT_HEALTH,
    "survival": THREAT_SURVIVAL,
}


# ---------------------------------------------------------------------------
# deadly_corridor
# ---------------------------------------------------------------------------
# A different problem: navigation under fire. Reward is distance travelled toward
# a vest 1312 units away, dying costs 100, and the scenario ships at doom_skill 5.
# Walking forward blindly and dying partway scores ~+600, which is the bar.
#
# Seven options in one `choice` rather than separate aim and move questions, to
# keep the battery at two questions. Latency is the binding constraint --
# defend_the_center already runs at 5.2 decisions/sec against a possible 8.75 --
# and a third question would cost more decisions than the finer control buys.
# `fire` stays separate, so the model can shoot while doing any of these.
#
# Criteria are written out in full deliberately: the terse experiment in
# TURN_APPROACH_TERSE cost more than half the score by making options unreachable.

# v1, kept as the record of a question that could not work. `advance` read "No
# enemy is blocking the way" -- and the corridor always has enemies in view, so the
# option was unreachable by construction. The model obeyed: over two episodes it
# chose aim_left 54%, aim_right 36%, hold 11%, advance **0%**, travelled **0%** of
# the corridor and scored -116. A faithful reading of an impossible instruction.
CORRIDOR_MOVE_BLOCKING = {
    "type": "choice",
    "instructions": (
        "The player is fighting down a corridor toward a green vest at the far end. "
        "Getting closer to the vest is the goal, but enemies along the corridor shoot back "
        "and dying ends the run. Choose what the player should do right now."
    ),
    "criteria": {
        "advance": "No enemy is blocking the way, so walk forward down the corridor toward the vest",
        "hold": "An enemy is centred in the crosshair, so stand still and shoot it",
        "aim_left": "An enemy is visible to the left of the crosshair, so turn left to aim at it",
        "aim_right": "An enemy is visible to the right of the crosshair, so turn right to aim at it",
        "dodge_left": "An enemy is shooting at the player, so sidestep to the left to avoid the shots",
        "dodge_right": "An enemy is shooting at the player, so sidestep to the right to avoid the shots",
        "retreat": "The player is badly hurt and about to die, so back away from the enemies",
    },
}

# v2. Advancing is the default and the criteria are keyed on *threat*, not on
# whether anything is visible at all. Distance is the discriminator the state
# already reports well ("close", "right on top of you", "far away"), and the
# instructions say plainly that standing still scores nothing -- which is literally
# true here, since the reward is distance travelled.
CORRIDOR_MOVE = {
    "type": "choice",
    "instructions": (
        "The player is fighting down a long corridor toward a green vest at the far end. "
        "Only getting closer to the vest scores points, so standing still achieves nothing and "
        "walking forward is the normal thing to do. Stop to fight only when an enemy is close "
        "enough to be a real threat. Enemies far down the corridor can be walked past."
    ),
    "criteria": {
        "advance": "Walk forward toward the vest. This is the right choice unless an enemy is close enough to be an immediate threat",
        "hold": "An enemy is centred in the crosshair right now, so stand still and shoot it",
        "aim_left": "An enemy is close and to the left of the crosshair, so turn left to aim at it before moving on",
        "aim_right": "An enemy is close and to the right of the crosshair, so turn right to aim at it before moving on",
        "dodge_left": "An enemy is close and shooting at the player, so sidestep left to avoid the shots",
        "dodge_right": "An enemy is close and shooting at the player, so sidestep right to avoid the shots",
        "retreat": "The player is badly hurt and about to die, so back away from the enemies",
    },
}

# v3. Four options. `dodge_left`, `dodge_right` and `retreat` were never chosen
# once across either earlier run, so they were only ever costing tokens -- and
# tokens are the binding constraint here: the seven-option question ran p50 126 ms
# against a 143 ms interval and skipped most of its slots.
CORRIDOR_MOVE_LEAN = {
    "type": "choice",
    "instructions": (
        "The player is fighting down a long corridor toward a green vest at the far end. "
        "Only getting closer to the vest scores points, so standing still achieves nothing and "
        "walking forward is the normal thing to do. Stop only to shoot an enemy that is close."
    ),
    "criteria": {
        "advance": "Walk forward toward the vest, which is right unless an enemy is close enough to be an immediate threat",
        "hold": "An enemy is centred in the crosshair right now, so stand still and shoot it",
        "aim_left": "An enemy is close and to the left of the crosshair, so turn left to aim at it",
        "aim_right": "An enemy is close and to the right of the crosshair, so turn right to aim at it",
    },
}

# v4. Two options: keep walking, or stop and shoot. The cheapest possible question
# for this map, and a fair test of whether aiming is worth its latency at all --
# the blind "walk forward and shoot" baseline scores ~528 without aiming once.
CORRIDOR_MOVE_BINARY = {
    "type": "choice",
    "instructions": (
        "The player is walking down a long corridor toward a green vest at the far end, with "
        "enemies along the way. Only getting closer to the vest scores points."
    ),
    "criteria": {
        "advance": "Keep walking forward toward the vest",
        "hold": "An enemy is close and in the way, so stop and shoot it",
    },
}

CORRIDOR_VARIANTS = {
    "blocking": CORRIDOR_MOVE_BLOCKING,
    "threat": CORRIDOR_MOVE,
    "lean": CORRIDOR_MOVE_LEAN,
    "binary": CORRIDOR_MOVE_BINARY,
}

CORRIDOR_BATTERY: dict[str, dict] = {
    "fire": FIRE_QUESTION,
    "move": CORRIDOR_MOVE,
}


# ---------------------------------------------------------------------------
# deathmatch
# ---------------------------------------------------------------------------
# The map where a typed decision model should have something to offer: 20 buttons,
# six weapon slots, pickups everywhere, and reward that counts only kills. Writing
# a good policy by hand here is genuinely awkward, which is the case distillation
# needs -- a teacher only worth distilling if it beats hand-written rules.
#
# Three questions, not two. Latency is not the constraint during **lockstep**
# harvesting, where the game does not advance while the model thinks, so the
# teacher can be asked for its best decisions rather than its fastest ones.

DEATHMATCH_MOVE = {
    "type": "choice",
    "instructions": (
        "The player is in a deathmatch arena full of enemies and pickups. Only killing enemies "
        "scores points. Choose how the player should move right now."
    ),
    "criteria": {
        "advance": "Enemies are visible or the way is clear, so move forward to cover ground and reach pickups",
        "scan": "No enemy is visible, so turn on the spot to search the arena for one",
        "hold": "An enemy is centred in the crosshair, so stand still and shoot it",
        "aim_left": "An enemy is visible to the left of the crosshair, so turn left to aim at it",
        "aim_right": "An enemy is visible to the right of the crosshair, so turn right to aim at it",
        "dodge_left": "An enemy is shooting at the player, so sidestep left to avoid the shots",
        "dodge_right": "An enemy is shooting at the player, so sidestep right to avoid the shots",
        "retreat": "The player is badly hurt and about to die, so back away from the enemies",
    },
}

# v1, kept as the record. It asked which weapon to hold without the state ever
# saying which weapons the player owned, so the model was choosing among weapons it
# might not be carrying -- and a switch to one it does not own presses a button that
# does nothing. Measured over 8 lockstep episodes it chose `pistol` 27% (Doom's worst
# weapon, and the criterion said pistol was a last resort), `shotgun` 19%, and `keep`
# only 2%, meaning it thrashed weapon switches almost every decision. The scripted
# baseline, by contrast, chose `keep` 11% and `chaingun` 39%.
DEATHMATCH_WEAPON_BLIND = {
    "type": "choice",
    "instructions": (
        "Choose which weapon the player should be holding. A shotgun or chaingun is reliable at "
        "most ranges, a rocket launcher hits hard but is dangerous up close, and a plasma rifle "
        "is strong when there is plasma ammunition for it. Only switch when it is worth the "
        "moment it costs, and never switch to a weapon the player has no ammunition for."
    ),
    "criteria": {
        "keep": "The weapon already in hand is a reasonable choice, so do not switch",
        "shotgun": "Switch to the shotgun, a dependable close and medium range weapon",
        "chaingun": "Switch to the chaingun, good for sustained fire at medium range",
        "rocket_launcher": "Switch to the rocket launcher for a distant or tough enemy, but not at close range",
        "plasma_rifle": "Switch to the plasma rifle for heavy sustained damage",
        "pistol": "Switch to the pistol, only if nothing better has ammunition",
    },
}

# v2. The state now lists what the player is carrying, so the question is
# answerable. Three changes beyond that:
#
#  * `keep` is stated as the default and named first, because switching costs a
#    moment and the measured failure was thrashing, not stickiness.
#  * `pistol` is gone. It is never the right answer when anything else is held, and
#    slot 2 is the starting weapon, so `keep` already covers it. Offering a bad
#    option invites it -- the corridor's `lean` variant showed the option set shapes
#    every answer rather than being a menu picked from independently.
#  * Every switch criterion says out loud that it only applies to a weapon the
#    player is actually carrying.
DEATHMATCH_WEAPON = {
    "type": "choice",
    "instructions": (
        "Choose which weapon the player should be holding. Switching weapons takes a moment "
        "during which the player cannot shoot, so keep the current weapon unless there is a "
        "clear reason to change. Only switch to a weapon the player is actually carrying; the "
        "state lists them. Never switch to a weapon that has no ammunition."
    ),
    "criteria": {
        "keep": "Keep the weapon already in hand. This is the right answer unless the current weapon is out of ammunition or clearly wrong for the situation",
        "shotgun": "Switch to the shotgun, if carrying one, for close and medium range",
        "chaingun": "Switch to the chaingun, if carrying one, for sustained fire at medium range",
        "rocket_launcher": "Switch to the rocket launcher, if carrying one, for a distant or tough enemy, but never at close range",
        "plasma_rifle": "Switch to the plasma rifle, if carrying one, for heavy sustained damage",
    },
}

# A move question that states the *strategy* rather than only describing options.
# Every option list so far has said what each choice means without saying what the
# player is trying to do, and the measured failures were all failures of priority:
# aiming forever instead of advancing, advancing forever instead of aiming. The
# ordering here is explicit so the model has something to rank against.
DEATHMATCH_MOVE_STRATEGY = {
    "type": "choice",
    # Instructions stay short on purpose. laya-mps caps the question *head* -- the
    # instructions alone -- at 192 tokens (`head_max_len`) and refuses the request
    # rather than silently truncating it. The first draft of this variant was
    # rejected outright with a 422.
    #
    # That cap is not a problem, because criteria are not subject to it, and the
    # earlier `turn` bench already showed criteria-led beating instruction-led
    # (98% against 85%). So the priority ordering lives in the criteria, each one
    # saying where it sits in the list rather than only what it means.
    "instructions": (
        "The player is in a deathmatch arena. Only killing enemies scores points, and the player "
        "cannot kill what it cannot see. Pick the first of these that applies."
    ),
    "criteria": {
        "hold": "FIRST: an enemy is centred in the crosshair, so stand still and keep shooting it",
        "aim_left": "SECOND: an enemy is visible to the left of the crosshair, so turn left until it is centred",
        "aim_right": "SECOND: an enemy is visible to the right of the crosshair, so turn right until it is centred",
        "retreat": "THIRD: the player is badly hurt and about to die, so back away",
        "dodge_left": "THIRD: an enemy is close and shooting, so sidestep left",
        "dodge_right": "THIRD: an enemy is close and shooting, so sidestep right",
        "grab": "FOURTH: no enemy needs dealing with and a pickup is nearby, so walk onto it",
        "scan": "LAST: nothing at all is visible, so turn on the spot to search for an enemy",
        "advance": "LAST: nothing needs dealing with and the way ahead is clear, so move forward to cover ground",
    },
}

DEATHMATCH_MOVE_VARIANTS = {
    "plain": DEATHMATCH_MOVE,
    "strategy": DEATHMATCH_MOVE_STRATEGY,
}

DEATHMATCH_WEAPON_VARIANTS = {
    "blind": DEATHMATCH_WEAPON_BLIND,
    "inventory": DEATHMATCH_WEAPON,
}

# Two questions, not three. The weapon question was **cut on evidence**, like
# `threat` before it: across 4 episodes each, the `blind` and `inventory` variants
# scored *identically* (+5.25 / +5.25, then +5.75 / +5.75), with identical kills and
# identical move distributions, despite answering completely differently -- `blind`
# chose pistol 39% of the time and `inventory` chose keep 40%.
#
# The harvest explains it: across 1436 lockstep ticks the player held the **pistol
# 100% of the time and never carried a second weapon**, so every weapon answer was a
# no-op. There was nothing to switch to. The question cost ~12 ms per decision
# (197 ms against 185 ms) and changed nothing at all.
#
# The cause is worth keeping in view: the model chooses `advance` only 0.8% of the
# time, so it stands and spins rather than walking to the weapons lying around it.
# That is what `grab` in the strategy variant is for -- give it the capability
# first, and the weapon question may become worth re-asking later.
DEATHMATCH_BATTERY: dict[str, dict] = {
    "fire": FIRE_QUESTION,
    "move": DEATHMATCH_MOVE_STRATEGY,
}
