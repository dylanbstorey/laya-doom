"""Baselines, so "LAYA plays Doom badly" is a measurement and not a disclaimer.

Both are ``DecisionClient`` implementations rather than separate loops. That
matters for fairness: a baseline reads the *same serialized state dict* LAYA
reads, runs through the same interval, the same latch and the same button
mapping, and differs only in how it arrives at an answer. Any gap is therefore
attributable to the decision procedure and nothing else.

The scripted policy is the bench's oracle, so it is close to the ceiling
available from this state representation -- exactly the comparison worth making.
"""

from __future__ import annotations

import random
import time

from .client import Answer, Decision

TURN_OPTIONS = ("left", "right", "hold", "scan", "advance")


def _certain(fire: bool, turn: str, latency_ms: float, model: str) -> Decision:
    """A Decision with no uncertainty, which is the honest thing for code to report."""
    probability = 1.0 if fire else 0.0
    return Decision(
        answers={
            "fire": Answer("fire", "noul", probability, {"true": probability, "false": 1 - probability}, 1.0),
            "turn": Answer("turn", "choice", turn, {option: 1.0 if option == turn else 0.0 for option in TURN_OPTIONS}, 1.0),
        },
        latency_ms=latency_ms,
        model=model,
    )


class ScriptedClient:
    """Turn toward the nearest enemy, fire when something is lined up.

    Reads only the fields LAYA is given. This is the oracle `bench/score.py`
    scores against, so it is effectively the best this state representation
    allows -- which is the point of putting it next to the model.
    """

    model = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        self.calls += 1

        fire = bool(state.get("an_enemy_is_lined_up_with_your_crosshair"))
        nearest = state.get("nearest_enemy")
        if not nearest:
            # Search, exactly as the model is offered the chance to. An earlier
            # version held still here, which flattered a scanning model by giving
            # the baseline a strictly smaller action space.
            turn = "scan"
        else:
            where = str(nearest.get("where", ""))
            if nearest.get("lined_up_with_crosshair"):
                # Aimed already: close the distance if the shot is long, else hold
                # and shoot. Same reasoning the model is offered.
                turn = "advance" if "far" in str(nearest.get("how_far", "")) else "hold"
            elif "left" in where:
                turn = "left"
            elif "right" in where:
                turn = "right"
            else:
                turn = "hold"
        return _certain(fire, turn, (time.perf_counter() - started) * 1000, self.model)

    def close(self) -> None:
        return None


class RandomClient:
    """Uniform noise, for the floor of the comparison."""

    model = "random"

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)
        self.calls = 0

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        self.calls += 1
        return _certain(
            self._rng.random() < 0.5,
            self._rng.choice(TURN_OPTIONS),
            (time.perf_counter() - started) * 1000,
            self.model,
        )

    def close(self) -> None:
        return None
