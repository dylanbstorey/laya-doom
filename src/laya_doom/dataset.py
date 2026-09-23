"""Load harvested lockstep decisions as a training set.

Filtered behavioural cloning: the teacher's *mean* is unremarkable -- on
deathmatch LAYA scored +3.9 against a scripted +5.6 -- but its best episodes reach
+11, well above the baseline's mean. A student trained only on the good runs is
not bounded by the teacher's average, only by its best.

Two things this is strict about:

* **Provenance.** Every row carries a fingerprint of the question battery that
  produced it, and the prompts changed six times during development. Mixing two
  policies into one dataset would be silent corruption, so a load covering more
  than one fingerprint has to say so out loud.
* **Soft targets.** The distributions are kept, not just the argmax. LAYA's
  calibrated probabilities are the thing it is actually good at, and a KL loss
  against them carries strictly more information than a hard label -- including
  the cases where the teacher was unsure, which are exactly the ones a student
  should not learn to be confident about.
"""

from __future__ import annotations

import gzip
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .features import FEATURE_NAMES


@dataclass
class Batch:
    """Features and soft targets, aligned row for row."""

    features: np.ndarray            # (n, 37)
    fire: np.ndarray                # (n,) P(true)
    move: np.ndarray                # (n, len(move_options)) probabilities
    move_options: list[str]
    episode_scores: np.ndarray      # (n,) the score of the episode each row came from
    weights: np.ndarray             # (n,) per-row weight, for score-weighted cloning

    def __len__(self) -> int:
        return len(self.features)

    def split(self, holdout: float = 0.2, seed: int = 0) -> tuple["Batch", "Batch"]:
        """Split by *episode*, never by row.

        Consecutive ticks inside one episode are near-duplicates, so a random row
        split would put near-copies of the training data in the test set and report
        a score that means nothing.
        """
        rng = np.random.default_rng(seed)
        episodes = np.unique(self.episode_ids)
        rng.shuffle(episodes)
        cut = max(1, int(len(episodes) * holdout))
        test_ids = set(episodes[:cut].tolist())
        mask = np.array([eid in test_ids for eid in self.episode_ids])
        return self._take(~mask), self._take(mask)

    episode_ids: np.ndarray = None  # type: ignore[assignment]

    def _take(self, mask: np.ndarray) -> "Batch":
        return Batch(
            features=self.features[mask],
            fire=self.fire[mask],
            move=self.move[mask],
            move_options=self.move_options,
            episode_scores=self.episode_scores[mask],
            weights=self.weights[mask],
            episode_ids=self.episode_ids[mask],
        )


def resolve(path: Path) -> Path:
    """Accept either the plain or the gzipped form of a harvest.

    Harvesting appends plain JSONL because appending to a gzip stream is a
    nuisance; the committed copy is gzipped because it compresses 13x -- the rows
    repeat their keys and most of their observation text.
    """
    if path.exists():
        return path
    gzipped = path.with_suffix(path.suffix + ".gz")
    if gzipped.exists():
        return gzipped
    return path


def read(path: Path) -> Iterator[dict]:
    path = resolve(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def describe(path: Path) -> dict:
    """What is on disk, before deciding what to keep."""
    rows = list(read(path))
    if not rows:
        return {"rows": 0}
    episodes: dict[tuple, float] = {}
    for row in rows:
        episodes[(row.get("run"), row.get("episode"))] = row.get("episode_score", 0.0)
    scores = sorted(episodes.values(), reverse=True)
    return {
        "rows": len(rows),
        "episodes": len(episodes),
        "batteries": dict(Counter(row.get("battery") for row in rows)),
        "scenarios": dict(Counter(row.get("scenario") for row in rows)),
        "best": scores[0],
        "median": statistics.median(scores),
        "worst": scores[-1],
        "scores": scores,
    }


def load(
    path: Path,
    *,
    move_question: str = "move",
    min_score: float | None = None,
    top_fraction: float | None = None,
    battery: str | None = None,
    scenario: str | None = None,
    weight_by_score: bool = False,
) -> Batch:
    """Read rows and keep the ones worth cloning.

    ``min_score`` keeps episodes at or above an absolute score; ``top_fraction``
    keeps the best share of episodes, which is the more robust choice when the
    score scale differs per scenario.
    """
    rows = [row for row in read(path) if move_question in row.get("answers", {})]
    if scenario:
        rows = [row for row in rows if row.get("scenario") == scenario]
    if battery:
        rows = [row for row in rows if row.get("battery") == battery]
    if not rows:
        raise ValueError(f"no usable rows in {path}")

    fingerprints = {row.get("battery") for row in rows}
    if len(fingerprints) > 1:
        raise ValueError(
            f"{path} mixes {len(fingerprints)} question batteries {sorted(fingerprints)}. "
            "Those are different policies; pass battery=... to pick one."
        )

    episode_score = {
        (row.get("run"), row.get("episode")): row.get("episode_score", 0.0) for row in rows
    }
    if top_fraction is not None:
        ranked = sorted(episode_score.items(), key=lambda pair: -pair[1])
        cut = max(1, int(len(ranked) * top_fraction))
        keep = {key for key, _ in ranked[:cut]}
        rows = [row for row in rows if (row.get("run"), row.get("episode")) in keep]
    elif min_score is not None:
        rows = [row for row in rows if row.get("episode_score", 0.0) >= min_score]
    if not rows:
        raise ValueError("the filter kept nothing; loosen min_score or top_fraction")

    # Option order comes from the first row and must hold for all of them, or the
    # target columns would not line up.
    options = list(rows[0]["answers"][move_question]["distribution"])
    features, fire, move, scores, ids = [], [], [], [], []
    for row in rows:
        answers = row["answers"]
        distribution = answers[move_question]["distribution"]
        if list(distribution) != options:
            raise ValueError("move options differ between rows; the battery changed mid-file")
        features.append(row["features"])
        fire.append(float(answers["fire"]["value"]))
        move.append([float(distribution[name]) for name in options])
        scores.append(float(row.get("episode_score", 0.0)))
        ids.append(f"{row.get('run')}:{row.get('episode')}")

    features_array = np.asarray(features, dtype=np.float32)
    if features_array.shape[1] != len(FEATURE_NAMES):
        raise ValueError(
            f"{features_array.shape[1]} features on disk, {len(FEATURE_NAMES)} expected -- "
            "the extractor changed since this file was harvested"
        )

    scores_array = np.asarray(scores, dtype=np.float32)
    if weight_by_score:
        # Lift to positive and normalise to mean 1, so a better episode counts for
        # more without any row counting for nothing.
        lifted = scores_array - scores_array.min() + 1.0
        weights = lifted / lifted.mean()
    else:
        weights = np.ones_like(scores_array)

    return Batch(
        features=features_array,
        fire=np.asarray(fire, dtype=np.float32),
        move=np.asarray(move, dtype=np.float32),
        move_options=options,
        episode_scores=scores_array,
        weights=weights.astype(np.float32),
        episode_ids=np.asarray(ids),
    )
