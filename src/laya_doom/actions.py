"""Typed answers -> a ViZDoom button vector.

The only place a model answer becomes a key press. Deliberately dumb: it
thresholds and looks up, and makes no decisions of its own. Anything cleverer
here would be the code playing Doom instead of the model.
"""

from __future__ import annotations

from typing import Any, Sequence

from .client import Decision

FIRE_THRESHOLD = 0.5

# Button names as ViZDoom reports them, mapped to the turn answer that presses them.
#
# `scan` is the model deciding to search rather than aim. Rendering it as a single
# consistent direction is mechanical execution of that intent, not a decision: a
# fixed direction sweeps the full room, which is what searching means when enemies
# can come from anywhere. Alternating would stall the view in one arc.
SCAN_DIRECTION = "right"
ATTACK_BUTTON = "ATTACK"
FORWARD_BUTTON = "MOVE_FORWARD"

# Every answer any battery can give, mapped to the one button that executes it.
# A single table across scenarios: the names do not collide, and an answer whose
# button the current map does not expose is simply inert (see from_answers).
#
# `scan` resolves to a single consistent direction because searching means sweeping
# an arc; alternating would stall the view inside it. `advance` is the model
# choosing to close distance -- Doom moves 3.3 units/tic, so a slow commitment.
ANSWER_BUTTONS: dict[str, str | None] = {
    # defend_the_center
    "left": "TURN_LEFT",
    "right": "TURN_RIGHT",
    "scan": "TURN_RIGHT",
    "advance": FORWARD_BUTTON,
    "hold": None,
    # deadly_corridor
    "aim_left": "TURN_LEFT",
    "aim_right": "TURN_RIGHT",
    "dodge_left": "MOVE_LEFT",
    "dodge_right": "MOVE_RIGHT",
    "retreat": "MOVE_BACKWARD",
    "stand": None,
}


def button_names(game: Any) -> list[str]:
    """Available button names, e.g. ``["TURN_LEFT", "TURN_RIGHT", "ATTACK"]``."""
    return [str(button).split(".")[-1] for button in game.get_available_buttons()]


def neutral(buttons: Sequence[str]) -> list[int]:
    """Press nothing. What the latch decays to between replies."""
    return [0] * len(buttons)


def from_answers(
    buttons: Sequence[str],
    *,
    fire: bool = False,
    turn: str = "hold",
) -> list[int]:
    """Build a button vector. Unavailable buttons are silently skipped."""
    action = neutral(buttons)
    index = {name: position for position, name in enumerate(buttons)}
    if fire and ATTACK_BUTTON in index:
        action[index[ATTACK_BUTTON]] = 1
    wanted = ANSWER_BUTTONS.get(turn)
    if wanted and wanted in index:
        action[index[wanted]] = 1
    return action


def from_decision(
    buttons: Sequence[str],
    decision: Decision,
    *,
    fire_threshold: float = FIRE_THRESHOLD,
) -> list[int]:
    """Translate a whole decision.

    ``fire`` is a ``noul``, so it arrives as P(true) and is thresholded. 0.5 is
    the honest default given the model reports calibrated probabilities -- the
    bench measured 94% specificity at this threshold.
    """
    fire_answer = decision.get("fire")
    # `turn` in defend_the_center, `move` in deadly_corridor -- both name the single
    # non-fire action for the tick, and both resolve through ANSWER_BUTTONS.
    move_answer = decision.get("turn") or decision.get("move")
    return from_answers(
        buttons,
        fire=bool(fire_answer and float(fire_answer.value) >= fire_threshold),
        turn=str(move_answer.value) if move_answer else "hold",
    )
