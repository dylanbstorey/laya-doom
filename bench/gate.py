"""The gate on distillation: does lockstep LAYA beat a hand-written policy?

A distilled student's ceiling is its teacher. On `defend_the_center` and
`deadly_corridor` a scripted policy reading the same state matched or beat LAYA,
so distilling there would spend real effort to reach something already written in
twenty lines. `deathmatch` is the honest candidate -- 20 buttons, six weapon
slots, pickups everywhere -- where hand-written rules get awkward.

Everything runs in **lockstep**: the game does not advance while the model
thinks, so inference costs no game time. That is the right setting for a teacher,
and it matters: on the same seed, lockstep scored +13 with 14 kills against
real time's +1 with 2 kills. Every earlier "LAYA loses to hand-rules" measurement
was taken on a latency-crippled version of it.

    uv run python bench/gate.py --scenario deathmatch --episodes 6
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
from laya_doom.baselines import (  # noqa: E402
    CorridorScriptedClient,
    DeathmatchScriptedClient,
    RandomCorridorClient,
    ScriptedClient,
)
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.game import make_game  # noqa: E402
from laya_doom.loop import MS_PER_TIC, DecisionLoop  # noqa: E402


def scripted_for(scenario) -> object:
    if scenario.name == "deathmatch":
        return DeathmatchScriptedClient()
    if scenario.has_goal:
        return CorridorScriptedClient()
    return ScriptedClient()


def run(name: str, client, scenario, episodes: int, seed: int, record: list | None = None) -> dict:
    scores, kills, answers, lat = [], [], Counter(), []

    for episode in range(episodes):
        game = make_game(scenario, seed=seed + episode)
        loop = DecisionLoop(
            game, client, scenario.battery,
            interval_ms=scenario.interval_tics * MS_PER_TIC,
            goal_x=scenario.goal_x,
            # Lockstep: the world waits while the model thinks.
            real_time=False,
            use_thread=False,
        )

        def on_tick(tick):
            if not (tick.fresh and tick.decision is not None):
                return
            lat.append(tick.decision.latency_ms)
            for qname, answer in tick.decision.answers.items():
                if answer.type == "choice":
                    answers[f"{qname}:{answer.value}"] += 1
            if record is not None:
                record.append({
                    "state": tick.state,
                    "answers": {
                        qname: {"type": a.type, "value": a.value,
                                "distribution": a.distribution, "confidence": a.confidence}
                        for qname, a in tick.decision.answers.items()
                    },
                })

        try:
            result = loop.run_episode(on_tick=on_tick)
        finally:
            loop.close()
            game.close()
        scores.append(result.score)
        kills.append(result.killcount)
        print(f"    {name}: ep{episode + 1} score={result.score:+7.1f} kills={result.killcount:.0f}", flush=True)

    total = sum(answers.values()) or 1
    summary = {
        "name": name,
        "mean_score": statistics.mean(scores),
        "sd": statistics.stdev(scores) if len(scores) > 1 else 0.0,
        "mean_kills": statistics.mean(kills),
        "p50_ms": statistics.median(lat) if lat else 0.0,
        "answers": {k: round(v / total, 3) for k, v in answers.most_common(10)},
        "samples": len(record) if record is not None else 0,
    }
    print(f"  {name:12s} score={summary['mean_score']:+8.1f} (sd {summary['sd']:6.1f}) "
          f"kills={summary['mean_kills']:5.1f} p50={summary['p50_ms']:.0f}ms", flush=True)
    print(f"    {summary['answers']}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="deathmatch")
    parser.add_argument("--episodes", type=int, default=6)
    parser.add_argument("--seed", type=int, default=8000)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--harvest", type=Path, help="write LAYA's lockstep decisions here as JSONL")
    args = parser.parse_args()

    scenario = scenarios.get(args.scenario)
    print(f"gate: {scenario.name}, lockstep, {args.episodes} episodes")
    print(f"  questions: {list(scenario.battery)}\n")

    results = []
    scripted = scripted_for(scenario)
    results.append(run("scripted", scripted, scenario, args.episodes, args.seed))
    scripted.close()

    random_client = RandomCorridorClient()
    results.append(run("random", random_client, scenario, args.episodes, args.seed))
    random_client.close()

    harvested: list = [] if args.harvest else None
    laya = LayaMpsClient(args.url)
    results.append(run("laya", laya, scenario, args.episodes, args.seed, record=harvested))
    laya.close()

    if args.harvest and harvested:
        args.harvest.parent.mkdir(parents=True, exist_ok=True)
        with args.harvest.open("w") as sink:
            for row in harvested:
                sink.write(json.dumps(row) + "\n")
        print(f"\nharvested {len(harvested)} lockstep decisions -> {args.harvest}")

    by_name = {r["name"]: r for r in results}
    laya_score, scripted_score = by_name["laya"]["mean_score"], by_name["scripted"]["mean_score"]
    gap = laya_score - scripted_score
    pooled = max(by_name["laya"]["sd"], by_name["scripted"]["sd"], 1e-9)
    print(f"\nGATE: laya {laya_score:+.1f} vs scripted {scripted_score:+.1f} "
          f"(gap {gap:+.1f}, sd {pooled:.1f})")
    if gap > pooled:
        print("  PASS - the teacher beats hand-written rules, so there is something to distil.")
    elif gap > 0:
        print("  INCONCLUSIVE - teacher ahead but inside one standard deviation. More episodes.")
    else:
        print("  FAIL - hand-written rules match or beat the teacher; distilling would only")
        print("         reproduce a policy that already exists and already runs at zero latency.")

    (Path(__file__).parent / "gate.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
