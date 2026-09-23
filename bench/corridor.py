"""Compare corridor question variants and baselines by episode score.

deadly_corridor has no labelled fixture oracle -- the right action depends on the
whole trajectory, not one frozen tick -- so variants are judged only by what they
score. The bar is `forward`: walking blindly into the corridor and shooting,
which banks several hundred points before dying, because the reward is distance
travelled.

    uv run python bench/corridor.py --episodes 4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom import scenarios  # noqa: E402
from laya_doom.baselines import AlwaysForwardClient, CorridorScriptedClient, RandomCorridorClient  # noqa: E402
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.game import make_game  # noqa: E402
from laya_doom.loop import MS_PER_TIC, DecisionLoop  # noqa: E402
from laya_doom.questions import CORRIDOR_VARIANTS, FIRE_QUESTION  # noqa: E402

SCENARIO = scenarios.DEADLY_CORRIDOR


def evaluate(name: str, client, battery: dict, episodes: int, seed: int, interval_tics: int) -> dict:
    scores, progress, moves, lat = [], [], Counter(), []
    fires = decisions = skipped = 0

    for episode in range(episodes):
        game = make_game(SCENARIO, seed=seed + episode)
        loop = DecisionLoop(game, client, battery,
                            interval_ms=interval_tics * MS_PER_TIC, goal_x=SCENARIO.goal_x)
        best = [0]

        def on_tick(record):
            nonlocal fires, decisions
            reached = record.state.get("percent_of_the_way_to_the_goal")
            if reached is not None:
                best[0] = max(best[0], reached)
            if record.fresh and record.decision is not None:
                decisions += 1
                lat.append(record.decision.latency_ms)
                move = record.decision.get("move")
                if move is not None:
                    moves[str(move.value)] += 1
                fire = record.decision.get("fire")
                if fire is not None and float(fire.value) >= 0.5:
                    fires += 1

        try:
            result = loop.run_episode(on_tick=on_tick)
        finally:
            loop.close()
            game.close()
        scores.append(result.score)
        progress.append(best[0])
        skipped += result.skipped_slots
        print(f"    {name}: ep{episode + 1} score={result.score:+7.0f} reached={best[0]:3d}%", flush=True)

    total = sum(moves.values()) or 1
    summary = {
        "name": name,
        "mean_score": statistics.mean(scores),
        "sd": statistics.stdev(scores) if len(scores) > 1 else 0.0,
        "mean_progress": statistics.mean(progress),
        "best_progress": max(progress),
        "fire_rate": fires / decisions if decisions else 0.0,
        "moves": {k: round(v / total, 3) for k, v in moves.most_common()},
        "p50_ms": statistics.median(lat) if lat else 0.0,
        "skipped": skipped / episodes,
    }
    print(f"  {name:22s} score={summary['mean_score']:+8.1f} (sd {summary['sd']:6.1f}) "
          f"reached={summary['mean_progress']:.0f}% best={summary['best_progress']}% "
          f"p50={summary['p50_ms']:.0f}ms skipped={summary['skipped']:.0f}", flush=True)
    print(f"    moves: {summary['moves']}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=4)
    parser.add_argument("--seed", type=int, default=4000)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval-tics", type=int, default=SCENARIO.interval_tics)
    parser.add_argument("--variant", action="append", help="limit to named variants")
    args = parser.parse_args()

    results = []
    print("baselines:", flush=True)
    for name, client in [("forward", AlwaysForwardClient()),
                         ("scripted", CorridorScriptedClient()),
                         ("random", RandomCorridorClient())]:
        results.append(evaluate(name, client, SCENARIO.battery, args.episodes, args.seed, args.interval_tics))
        client.close()

    print("\nlaya, by question variant:", flush=True)
    chosen = args.variant or list(CORRIDOR_VARIANTS)
    client = LayaMpsClient(args.url)
    for name in chosen:
        battery = {"fire": FIRE_QUESTION, "move": CORRIDOR_VARIANTS[name]}
        results.append(evaluate(f"laya/{name}", client, battery, args.episodes, args.seed, args.interval_tics))
    client.close()

    (Path(__file__).parent / "corridor.json").write_text(json.dumps(results, indent=1))
    print("\nwrote bench/corridor.json")


if __name__ == "__main__":
    main()
