"""Does the `threat` score respond to health at all?

The main bench showed it moving 0.90 -> 1.07 on a 0-2 scale between healthy and
hurt states, which is close to no signal. Before cutting the question, give it a
fair trial: three phrasings, and a *paired* test that holds the geometry fixed
and varies only health, so nothing else can explain a difference.

    uv run python bench/threat.py
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.questions import THREAT_VARIANTS  # noqa: E402
from laya_doom.state import from_fixture, serialize  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
HEALTH_SWEEP = [100.0, 75.0, 50.0, 25.0, 5.0]


def engaged_states(limit: int = 6):
    """Real ticks with an enemy in sight, so 'threat' has something to rate."""
    out = []
    for path in sorted(FIXTURES.glob("*.json")):
        for fixture in json.loads(path.read_text()):
            observation = from_fixture(fixture)
            if observation.nearest is not None:
                out.append(observation)
            if len(out) >= limit:
                return out
    return out


def main() -> None:
    client = LayaMpsClient()
    questions = {name: question for name, question in THREAT_VARIANTS.items()}
    base = engaged_states()
    for _ in range(2):
        client.decide(serialize(base[0]), questions)

    # variant -> health -> [scores]
    scores: dict[str, dict[float, list[float]]] = {name: {h: [] for h in HEALTH_SWEEP} for name in questions}
    confidences: dict[str, list[float]] = {name: [] for name in questions}

    for observation in base:
        for health in HEALTH_SWEEP:
            decision = client.decide(serialize(replace(observation, health=health)), questions)
            for name, answer in decision.answers.items():
                scores[name][health].append(float(answer.value))
                confidences[name].append(answer.confidence)
    client.close()

    print(f"paired health sweep over {len(base)} fixed geometries, scale 0-2\n")
    rows = []
    for name in questions:
        means = {health: statistics.mean(values) for health, values in scores[name].items()}
        span = means[5.0] - means[100.0]
        # Spearman-free monotonicity check: does the mean rise as health falls?
        ordered = [means[h] for h in HEALTH_SWEEP]  # health descending
        monotone = all(later >= earlier - 1e-9 for earlier, later in zip(ordered, ordered[1:]))
        rows.append((name, means, span, monotone, statistics.mean(confidences[name])))
        sweep = "  ".join(f"hp{int(h):>3}={means[h]:.2f}" for h in HEALTH_SWEEP)
        print(f"{name:10s} {sweep}   span={span:+.2f} monotone={monotone} conf={statistics.mean(confidences[name]):.3f}")

    best = max(rows, key=lambda row: row[2])
    print(f"\nlargest response to health: {best[0]} (span {best[2]:+.2f} over a 2.0 scale)")
    print("verdict:", "keep" if best[2] >= 0.5 else "CUT - the score barely tracks health")


if __name__ == "__main__":
    main()
