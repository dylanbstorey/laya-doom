"""A distilled student: LAYA's policy as a small network over features.

Why this exists is a rate argument, not an intelligence one. LAYA answers in
80-190 ms, so the loop runs at 5-8 Hz and skips 20-65 slots an episode. This
network is a two-layer MLP over 37 features; a forward pass is a few matrix
multiplies in numpy and costs microseconds, so it can decide **every tic, 35 Hz**.
We have measured repeatedly that decision rate tracks score.

It is trained on LAYA's calibrated probability *distributions*, not its argmaxes.
On real harvested data the argmax view says the teacher uses four of nine options;
the probability mass says `advance` carries 10%, `dodge` 13% and `retreat` 7%.
Hard labels would discard all of that.

Inference deliberately depends only on numpy, so a trained student loads and runs
without torch.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .client import Answer, Decision
from .features import FEATURE_NAMES, features_from_state


def _softmax(x: np.ndarray) -> np.ndarray:
    shifted = x - x.max(axis=-1, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / exponentiated.sum(axis=-1, keepdims=True)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class Student:
    """Weights plus the vocabulary they were trained against."""

    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray
    w_fire: np.ndarray
    b_fire: np.ndarray
    w_move: np.ndarray
    b_move: np.ndarray
    move_options: list[str]
    move_question: str = "move"
    metadata: dict | None = None

    def forward(self, features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Features -> (P(fire), move distribution). Batched or single row."""
        single = features.ndim == 1
        x = features.reshape(1, -1) if single else features
        hidden = np.tanh(x @ self.w1 + self.b1)
        hidden = np.tanh(hidden @ self.w2 + self.b2)
        fire = _sigmoid(hidden @ self.w_fire + self.b_fire).reshape(-1)
        move = _softmax(hidden @ self.w_move + self.b_move)
        return (fire[0], move[0]) if single else (fire, move)

    @property
    def parameters(self) -> int:
        return sum(a.size for a in (self.w1, self.b1, self.w2, self.b2,
                                    self.w_fire, self.b_fire, self.w_move, self.b_move))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2,
            w_fire=self.w_fire, b_fire=self.b_fire, w_move=self.w_move, b_move=self.b_move,
            move_options=np.array(self.move_options),
            move_question=np.array(self.move_question),
            metadata=np.array(json.dumps(self.metadata or {})),
        )

    @classmethod
    def load(cls, path: Path) -> "Student":
        blob = np.load(path, allow_pickle=False)
        return cls(
            w1=blob["w1"], b1=blob["b1"], w2=blob["w2"], b2=blob["b2"],
            w_fire=blob["w_fire"], b_fire=blob["b_fire"],
            w_move=blob["w_move"], b_move=blob["b_move"],
            move_options=[str(o) for o in blob["move_options"]],
            move_question=str(blob["move_question"]),
            metadata=json.loads(str(blob["metadata"])),
        )


class StudentClient:
    """A trained student behind the same interface as LAYA.

    Drops into the loop, the baselines table and the web UI unchanged, which is
    what makes a like-for-like comparison possible: same state, same latch, same
    button mapping -- only the decision procedure and its speed differ.
    """

    model = "student"

    def __init__(self, student: Student | Path) -> None:
        self._student = student if isinstance(student, Student) else Student.load(student)
        self.calls = 0

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        self.calls += 1

        features = np.asarray(features_from_state(state), dtype=np.float32)
        fire, move = self._student.forward(features)
        options = self._student.move_options
        distribution = {name: float(p) for name, p in zip(options, move)}
        chosen = options[int(np.argmax(move))]

        # Confidence on the same normalised-negentropy scale the teacher's answers
        # use, so the UI's low-confidence marking means the same thing for both.
        from .client import _negentropy_confidence

        return Decision(
            answers={
                "fire": Answer("fire", "noul", float(fire),
                               {"true": float(fire), "false": 1.0 - float(fire)},
                               _negentropy_confidence([float(fire), 1.0 - float(fire)])),
                self._student.move_question: Answer(
                    self._student.move_question, "choice", chosen, distribution,
                    _negentropy_confidence(list(distribution.values())),
                ),
            },
            latency_ms=(time.perf_counter() - started) * 1000,
            model=self.model,
        )

    def close(self) -> None:
        return None


def new(move_options: list[str], *, hidden: int = 128, seed: int = 0,
        move_question: str = "move") -> Student:
    """A randomly initialised student, for training to fill in."""
    rng = np.random.default_rng(seed)
    inputs = len(FEATURE_NAMES)

    def layer(fan_in: int, fan_out: int) -> tuple[np.ndarray, np.ndarray]:
        scale = np.sqrt(1.0 / fan_in)
        return (rng.normal(0, scale, (fan_in, fan_out)).astype(np.float32),
                np.zeros(fan_out, dtype=np.float32))

    w1, b1 = layer(inputs, hidden)
    w2, b2 = layer(hidden, hidden)
    w_fire, b_fire = layer(hidden, 1)
    w_move, b_move = layer(hidden, len(move_options))
    return Student(w1, b1, w2, b2, w_fire, b_fire, w_move, b_move,
                   move_options=list(move_options), move_question=move_question)
