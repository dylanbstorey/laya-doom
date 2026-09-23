"""Collect LAYA's lockstep decisions as a training set for a distilled student.

Lockstep matters: the game does not advance while the model thinks, so the teacher
is asked for its best decisions rather than its fastest. Measured on one seed of
`defend_the_center`, lockstep scored +13 with 14 kills against real time's +1 with
2 kills -- the whole gap a student would be closing.

Every row carries the episode's final score, so training can keep only the good
runs. It also carries a fingerprint of the question battery that produced it,
because the prompts have changed repeatedly and mixing policies in one dataset
would be silent corruption.

Resumable: appends, and reports what is already on disk before adding to it.

    uv run python bench/harvest.py --scenario defend_the_center --episodes 40
    uv run python bench/harvest.py --scenario deathmatch --episodes 30 --seed 50000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom import scenarios  # noqa: E402
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.features import FEATURE_NAMES, features_from_state  # noqa: E402
from laya_doom.game import make_game  # noqa: E402
from laya_doom.loop import MS_PER_TIC, DecisionLoop  # noqa: E402

DATA = Path(__file__).parent.parent / "data"


def battery_fingerprint(battery: dict) -> str:
    """Short hash of the exact questions asked, so provenance is checkable."""
    blob = json.dumps(battery, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def describe(path: Path) -> None:
    if not path.exists():
        print(f"  {path.name}: empty")
        return
    rows = [json.loads(line) for line in path.open()]
    if not rows:
        print(f"  {path.name}: empty")
        return
    episodes = {(r.get("run"), r.get("episode")): r.get("episode_score", 0.0) for r in rows}
    scores = sorted(episodes.values(), reverse=True)
    batteries = Counter(r.get("battery") for r in rows)
    print(f"  {path.name}: {len(rows)} rows over {len(episodes)} episodes")
    print(f"    scores: best {scores[0]:+.0f}, median {statistics.median(scores):+.0f}, worst {scores[-1]:+.0f}")
    print(f"    batteries present: {dict(batteries)}")


def harvest(scenario, client, episodes: int, seed: int, out: Path, run_id: str) -> dict:
    fingerprint = battery_fingerprint(scenario.battery)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept, scores = 0, []
    started = time.time()

    with out.open("a") as sink:
        for episode in range(episodes):
            rows: list[dict] = []
            game = make_game(scenario, seed=seed + episode)
            loop = DecisionLoop(
                game, client, scenario.battery,
                interval_ms=scenario.interval_tics * MS_PER_TIC,
                goal_x=scenario.goal_x,
                real_time=False,   # lockstep: inference costs no game time
                use_thread=False,
            )

            def on_tick(tick):
                if not (tick.fresh and tick.decision is not None):
                    return
                rows.append({
                    "state": tick.state,
                    "features": features_from_state(tick.state),
                    "answers": {
                        name: {
                            "type": answer.type,
                            "value": answer.value,
                            "distribution": answer.distribution,
                            "confidence": answer.confidence,
                        }
                        for name, answer in tick.decision.answers.items()
                    },
                    "tick": tick.tick,
                })

            try:
                result = loop.run_episode(on_tick=on_tick)
            finally:
                loop.close()
                game.close()

            for position, row in enumerate(rows):
                row.update({
                    "run": run_id,
                    "episode": episode,
                    "episode_score": result.score,
                    "episode_kills": result.killcount,
                    "episode_length": len(rows),
                    "tick_index": position,
                    "scenario": scenario.name,
                    "battery": fingerprint,
                })
                sink.write(json.dumps(row) + "\n")
            sink.flush()

            kept += len(rows)
            scores.append(result.score)
            elapsed = time.time() - started
            print(f"  ep{episode + 1:3d}/{episodes} score={result.score:+8.1f} "
                  f"kills={result.killcount:3.0f} rows={len(rows):4d} "
                  f"total={kept:6d} [{elapsed / (episode + 1):.0f}s/ep]", flush=True)

    return {"rows": kept, "scores": scores, "fingerprint": fingerprint}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="defend_the_center")
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20000)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    scenario = scenarios.get(args.scenario)
    out = args.out or DATA / f"{scenario.name}.jsonl"

    print(f"harvesting {scenario.name}, {args.episodes} lockstep episodes, seed {args.seed}")
    print(f"  questions: {list(scenario.battery)}  battery={battery_fingerprint(scenario.battery)}")
    print(f"  features: {len(FEATURE_NAMES)}")
    print("already on disk:")
    describe(out)
    print()

    client = LayaMpsClient(args.url)
    try:
        summary = harvest(scenario, client, args.episodes, args.seed, out, run_id=f"{int(time.time())}")
    finally:
        client.close()

    scores = sorted(summary["scores"], reverse=True)
    good = [s for s in scores if s >= statistics.median(scores)]
    print(f"\nadded {summary['rows']} rows from {len(scores)} episodes")
    print(f"  scores: best {scores[0]:+.0f}, median {statistics.median(scores):+.0f}, worst {scores[-1]:+.0f}")
    print(f"  {len(good)} episodes at or above median -- the pool for filtered cloning")
    print("\nnow on disk:")
    describe(out)


if __name__ == "__main__":
    main()
