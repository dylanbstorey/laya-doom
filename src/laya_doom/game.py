"""ViZDoom setup, in one place.

`defend_the_center` is the starting scenario: the player is fixed in place with
only turn and attack, and enemies close in from all sides, which isolates
reactive aim-and-fire with no navigation. `deadly_corridor` adds the navigation
-- see `scenarios.py` for what differs between them.
"""

from __future__ import annotations

import os
from typing import Any

import vizdoom as vzd

from .scenarios import Scenario, get as get_scenario

DEFAULT_SCENARIO = "defend_the_center"


def make_game(
    scenario: str | Scenario = DEFAULT_SCENARIO,
    *,
    window: bool = False,
    resolution: Any = vzd.ScreenResolution.RES_320X240,
    seed: int | None = None,
) -> vzd.DoomGame:
    config = scenario if isinstance(scenario, Scenario) else get_scenario(scenario)
    game = vzd.DoomGame()
    game.load_config(os.path.join(vzd.scenarios_path, f"{config.name}.cfg"))
    game.set_window_visible(window)
    game.set_screen_resolution(resolution)
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    # The label buffer is how enemies are located at all -- see state.py.
    game.set_labels_buffer_enabled(True)
    for button in config.extra_buttons:
        if button not in game.get_available_buttons():
            game.add_available_button(button)
    game.set_available_game_variables(config.game_variables)
    if seed is not None:
        game.set_seed(seed)
    game.init()
    return game
