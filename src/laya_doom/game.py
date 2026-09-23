"""ViZDoom setup, in one place.

`defend_the_center` is the primary scenario: the player is fixed in place with
only turn and attack, and enemies close in from all sides. That isolates
reactive aim-and-fire with no navigation, which is the narrowest honest test of
a System 1 control loop.
"""

from __future__ import annotations

import os
from typing import Any

import vizdoom as vzd

DEFAULT_SCENARIO = "defend_the_center"

# defend_the_center.cfg exposes only TURN_LEFT, TURN_RIGHT and ATTACK. Movement is
# added on top so the model can close on a distant target: measured at 3.3 units
# per tic, against an arena radius of about 812.
EXTRA_BUTTONS = [vzd.Button.MOVE_FORWARD]

GAME_VARIABLES = [
    vzd.GameVariable.HEALTH,
    vzd.GameVariable.AMMO2,
    vzd.GameVariable.KILLCOUNT,
]


def make_game(
    scenario: str = DEFAULT_SCENARIO,
    *,
    window: bool = False,
    resolution: Any = vzd.ScreenResolution.RES_320X240,
    seed: int | None = None,
) -> vzd.DoomGame:
    game = vzd.DoomGame()
    game.load_config(os.path.join(vzd.scenarios_path, f"{scenario}.cfg"))
    game.set_window_visible(window)
    game.set_screen_resolution(resolution)
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    # The label buffer is how enemies are located at all -- see state.py.
    game.set_labels_buffer_enabled(True)
    for button in EXTRA_BUTTONS:
        if button not in game.get_available_buttons():
            game.add_available_button(button)
    game.set_available_game_variables(GAME_VARIABLES)
    if seed is not None:
        game.set_seed(seed)
    game.init()
    return game
