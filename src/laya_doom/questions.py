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

# The same five options, written short. Question text is re-tokenised on every tick,
# so criteria length is paid for continuously. An interleaved A/B -- alternating the
# two forms request-by-request on identical states, so ambient machine load falls on
# both equally -- measured a 30% smaller payload (656 -> 462 chars) buying 10.6 ms:
# p50 84.2 ms verbose against 73.6 ms terse, pooled sd 10.3 ms.
#
# That is a real but modest effect, and worth recording because the first reading of
# it was wrong. Episode latency had risen to ~98 ms p50 and this was attributed to
# the longer question; in fact most of that was other work on the machine, which the
# separate before/after runs never controlled for. Interleaving is what separated the
# two, and the honest split is ~10 ms of question length on top of a noisy baseline.

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
