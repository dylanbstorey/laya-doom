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
CORRIDOR_OPTIONS = ("advance", "hold", "aim_left", "aim_right", "dodge_left", "dodge_right", "retreat")


def _certain(
    fire: bool,
    turn: str,
    latency_ms: float,
    model: str,
    options=TURN_OPTIONS,
    name: str = "turn",
) -> Decision:
    """A Decision with no uncertainty, which is the honest thing for code to report.

    ``name`` is passed rather than inferred from the answer: `advance` and `hold`
    belong to both action spaces, so inferring mislabelled every corridor decision
    that used one of them as a `turn`.
    """
    probability = 1.0 if fire else 0.0
    return Decision(
        answers={
            "fire": Answer("fire", "noul", probability, {"true": probability, "false": 1 - probability}, 1.0),
            name: Answer(name, "choice", turn, {option: 1.0 if option == turn else 0.0 for option in options}, 1.0),
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


class AlwaysForwardClient:
    """Walk forward, shoot constantly, never aim. The bar for deadly_corridor.

    Worth reporting because it is embarrassingly strong: the scenario's reward is
    distance travelled, so a policy that simply walks into the corridor and dies
    partway still banks several hundred points. Any smarter policy has to beat
    *this*, not zero.
    """

    model = "always-forward"

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        self.calls += 1
        return _certain(True, "advance", (time.perf_counter() - started) * 1000, self.model,
                        options=CORRIDOR_OPTIONS, name="move")

    def close(self) -> None:
        return None


class CorridorScriptedClient:
    """Reference policy for deadly_corridor, reading only what LAYA is given.

    Stop and shoot what is lined up, turn toward what is not, back off when nearly
    dead, otherwise press on toward the vest.
    """

    model = "scripted"

    def __init__(self, retreat_health: float = 25.0) -> None:
        self.retreat_health = retreat_health
        self.calls = 0

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        self.calls += 1

        lined_up = bool(state.get("an_enemy_is_lined_up_with_your_crosshair"))
        nearest = state.get("nearest_enemy")
        health = float(state.get("health", 100))

        if health <= self.retreat_health and nearest:
            move = "retreat"
        elif lined_up:
            move = "hold"
        elif nearest:
            where = str(nearest.get("where", ""))
            move = "aim_left" if "left" in where else "aim_right" if "right" in where else "advance"
        else:
            move = "advance"
        return _certain(lined_up, move, (time.perf_counter() - started) * 1000, self.model,
                        options=CORRIDOR_OPTIONS, name="move")

    def close(self) -> None:
        return None


class RandomCorridorClient:
    """Uniform noise over the corridor's action space."""

    model = "random"

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)
        self.calls = 0

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        self.calls += 1
        return _certain(self._rng.random() < 0.5, self._rng.choice(CORRIDOR_OPTIONS),
                        (time.perf_counter() - started) * 1000, self.model,
                        options=CORRIDOR_OPTIONS, name="move")

    def close(self) -> None:
        return None
