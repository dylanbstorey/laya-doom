"""Play episodes with LAYA and with the baselines, and report both honestly.

    uv run python play.py                      # LAYA plus both baselines
    uv run python play.py --policy laya -n 3
    uv run python play.py --window             # watch it in a Doom window

Needs a laya-mps server for the `laya` policy:

    cd ../laya-mps && ./scripts/serve.sh --memory full --question-batch-size 4
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from laya_doom.baselines import RandomClient, ScriptedClient  # noqa: E402
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.game import DEFAULT_SCENARIO, make_game  # noqa: E402
from laya_doom.loop import DECISION_INTERVAL_MS, DecisionLoop, EpisodeResult  # noqa: E402
from laya_doom.questions import BATTERY  # noqa: E402

POLICIES = ("laya", "scripted", "random")


def build_client(policy: str, url: str):
    if policy == "laya":
        return LayaMpsClient(url)
    if policy == "scripted":
        return ScriptedClient()
    return RandomClient()


def play(policy: str, args) -> list[EpisodeResult]:
    client = build_client(policy, args.url)
    results = []
    for episode in range(1, args.episodes + 1):
        game = make_game(args.scenario, window=args.window, seed=args.seed + episode)
        loop = DecisionLoop(
            game, client, BATTERY,
            interval_ms=args.interval,
            fire_threshold=args.fire_threshold,
            real_time=not args.fast,
        )
        try:
            result = loop.run_episode(max_ticks=args.max_ticks)
        finally:
            loop.close()
            game.close()
        results.append(result)
        print(f"  {policy} episode {episode}: {result.summary()}")
    client.close()
    return results


def report(all_results: dict[str, list[EpisodeResult]], interval_ms: float) -> None:
    print("\n" + "=" * 78)
    print("Episode scores. The scripted baseline reads the same state dict LAYA reads,")
    print(f"at the same {interval_ms:.0f} ms cadence, through the same latch -- only the")
    print("decision procedure differs.")
    print("=" * 78)
    print(f"\n{'policy':10s} {'mean score':>11s} {'kills':>7s} {'decisions/s':>12s} "
          f"{'p50 ms':>8s} {'p95 ms':>8s} {'skipped':>8s}")
    for policy, results in all_results.items():
        if not results:
            continue
        scores = [r.score for r in results]
        latencies = [ms for r in results for ms in r.latencies_ms]
        rates = [r.decisions_per_second for r in results if r.decisions_per_second]
        print(
            f"{policy:10s} {statistics.mean(scores):11.1f} "
            f"{statistics.mean(r.killcount for r in results):7.1f} "
            f"{statistics.mean(rates) if rates else 0:12.1f} "
            f"{statistics.median(latencies) if latencies else 0:8.1f} "
            f"{sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)] if latencies else 0:8.1f} "
            f"{statistics.mean(r.skipped_slots for r in results):8.1f}"
        )
    if "laya" in all_results and "scripted" in all_results and all_results["laya"] and all_results["scripted"]:
        laya = statistics.mean(r.score for r in all_results["laya"])
        scripted = statistics.mean(r.score for r in all_results["scripted"])
        print(f"\nLAYA scores {laya / scripted:.0%} of the scripted baseline."
              if scripted else "\nScripted baseline scored zero; no ratio to report.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("-n", "--episodes", type=int, default=2)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--interval", type=float, default=DECISION_INTERVAL_MS)
    parser.add_argument("--fire-threshold", type=float, default=0.5)
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--window", action="store_true", help="show the Doom window")
    parser.add_argument("--fast", action="store_true", help="do not pace to real time")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    policies = POLICIES if args.policy == "all" else (args.policy,)
    all_results: dict[str, list[EpisodeResult]] = {}
    for policy in policies:
        print(f"\n{policy}:")
        all_results[policy] = play(policy, args)
    report(all_results, args.interval)


if __name__ == "__main__":
    main()
