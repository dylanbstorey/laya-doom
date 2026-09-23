"""Per-scenario configuration.

`defend_the_center` and `deadly_corridor` are different problems, not the same
problem with more buttons. The first is a fixed-position aim-and-fire task; the
second is navigation under fire, where the reward is distance travelled toward a
vest at the far end and dying costs 100. They need different action spaces,
different state text and different cadences, so each gets a `Scenario`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import vizdoom as vzd

from . import questions


@dataclass(frozen=True)
class Scenario:
    """Everything that varies between the maps LAYA plays."""

    name: str
    battery: dict
    interval_tics: int
    game_variables: list
    extra_buttons: list = field(default_factory=list)
    # Distance along +X to the goal, when the map has one. deadly_corridor's vest
    # sits at x=1312; measured, and the label confirms it at episode start.
    goal_x: float | None = None
    # A blind reference policy worth reporting because it is embarrassingly strong.
    notes: str = ""

    @property
    def has_goal(self) -> bool:
        return self.goal_x is not None


DEFEND_THE_CENTER = Scenario(
    name="defend_the_center",
    battery=questions.BATTERY,
    interval_tics=4,
    game_variables=[vzd.GameVariable.HEALTH, vzd.GameVariable.AMMO2, vzd.GameVariable.KILLCOUNT],
    extra_buttons=[vzd.Button.MOVE_FORWARD],  # the cfg exposes only turn and attack
)

DEADLY_CORRIDOR = Scenario(
    name="deadly_corridor",
    battery=questions.CORRIDOR_BATTERY,
    # 5 tics (142.9 ms) rather than 4. The corridor question offers seven options
    # and is correspondingly longer to tokenise, and a corridor is less frantic
    # than being surrounded -- so buy latency headroom instead of skipping slots.
    interval_tics=5,
    game_variables=[
        vzd.GameVariable.HEALTH,
        vzd.GameVariable.AMMO2,
        vzd.GameVariable.KILLCOUNT,
        vzd.GameVariable.POSITION_X,
        vzd.GameVariable.POSITION_Y,
    ],
    goal_x=1312.0,
    notes="Reward is distance travelled; dying costs 100. Walking forward blindly scores ~+600.",
)

ALL = {scenario.name: scenario for scenario in (DEFEND_THE_CENTER, DEADLY_CORRIDOR)}
DEFAULT = DEFEND_THE_CENTER


def get(name: str) -> Scenario:
    """Look up a scenario, falling back to a generic config for unlisted maps."""
    if name in ALL:
        return ALL[name]
    return Scenario(
        name=name,
        battery=questions.BATTERY,
        interval_tics=4,
        game_variables=DEFEND_THE_CENTER.game_variables,
    )
