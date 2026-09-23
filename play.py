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

from laya_doom import scenarios  # noqa: E402
from laya_doom.baselines import (  # noqa: E402
    AlwaysForwardClient,
    CorridorScriptedClient,
    RandomClient,
    RandomCorridorClient,
    ScriptedClient,
)
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.game import DEFAULT_SCENARIO, make_game  # noqa: E402
from laya_doom.loop import MS_PER_TIC, DecisionLoop, EpisodeResult  # noqa: E402

POLICIES = ("laya", "student", "scripted", "random", "forward")
# Policies that answer in well under a tic and should be called inline.
INSTANT_POLICIES = frozenset({"student", "scripted", "random", "forward"})


def build_client(policy: str, url: str, scenario, student_path=None):
    """Baselines differ per scenario, because the action spaces differ."""
    corridor = scenario.has_goal
    if policy == "laya":
        return LayaMpsClient(url)
    if policy == "student":
        from laya_doom.student import StudentClient

        return StudentClient(student_path)
    if policy == "scripted":
        if scenario.name == "deathmatch":
            from laya_doom.baselines import DeathmatchScriptedClient

            return DeathmatchScriptedClient()
        return CorridorScriptedClient() if corridor else ScriptedClient()
    if policy == "forward":
        return AlwaysForwardClient()
    return RandomCorridorClient() if corridor else RandomClient()


def play(policy: str, args) -> list[EpisodeResult]:
    scenario = scenarios.get(args.scenario)
    client = build_client(policy, args.url, scenario, args.student)
    # A student costs ~14 microseconds a decision, so it can afford to decide every
    # tic. Letting it run at the teacher's 6-tic cadence would throw away the only
    # advantage it has.
    tics = args.interval_tics or (1 if policy == "student" else scenario.interval_tics)
    interval = args.interval if args.interval else tics * MS_PER_TIC
    results = []
    for episode in range(1, args.episodes + 1):
        game = make_game(scenario, window=args.window, seed=args.seed + episode)
        loop = DecisionLoop(
            game, client, scenario.battery,
            interval_ms=interval,
            fire_threshold=args.fire_threshold,
            real_time=not args.fast,
            goal_x=scenario.goal_x,
            # A sub-millisecond policy is slower through a worker thread than it is
            # inline: the handoff does not finish inside one tic, so the next slot
            # finds a request still in flight and gets skipped. Measured at a 1-tic
            # cadence, the student managed 17.6 decisions/sec and skipped 234 slots
            # per episode purely to threading overhead.
            use_thread=policy not in INSTANT_POLICIES,
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
    print("Episode scores. Every policy reads the same state dict through the same latch")
    print("and the same button mapping. A student decides every tic because it can;")
    print("LAYA decides on the scenario's cadence because that is as fast as it answers.")
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
    for policy in ("forward", "random"):
        if policy in all_results and all_results[policy] and all_results.get("laya"):
            laya = statistics.mean(r.score for r in all_results["laya"])
            other = statistics.mean(r.score for r in all_results[policy])
            verdict = "beats" if laya > other else "LOSES TO"
            print(f"LAYA {verdict} the {policy} baseline: {laya:+.1f} vs {other:+.1f}")
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
    parser.add_argument("--interval", type=float, default=None,
                        help="ms between decisions; default is the scenario's own cadence")
    parser.add_argument("--interval-tics", type=int, default=None,
                        help="cadence in tics; a student defaults to 1 (every tic)")
    parser.add_argument("--student", type=Path, default=Path("models/deathmatch_student.npz"),
                        help="trained student weights for --policy student")
    parser.add_argument("--fire-threshold", type=float, default=0.5)
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--window", action="store_true", help="show the Doom window")
    parser.add_argument("--fast", action="store_true", help="do not pace to real time")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    scenario = scenarios.get(args.scenario)
    if args.policy == "all":
        # `forward` only means anything on a map with somewhere to go.
        policies = POLICIES if scenario.has_goal else tuple(p for p in POLICIES if p != "forward")
    else:
        policies = (args.policy,)
    print(f"scenario: {scenario.name}  cadence: {scenario.interval_tics} tics  "
          f"questions: {list(scenario.battery)}")
    if scenario.notes:
        print(f"  {scenario.notes}")
    all_results: dict[str, list[EpisodeResult]] = {}
    for policy in policies:
        print(f"\n{policy}:")
        all_results[policy] = play(policy, args)
    report(all_results, args.interval or scenario.interval_tics * MS_PER_TIC)


if __name__ == "__main__":
    main()
