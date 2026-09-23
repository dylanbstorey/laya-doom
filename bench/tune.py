"""Sweep the policy's tunable levers and measure mean episode score.

Model accuracy is not the bottleneck -- the shipped battery scores 97-100% on
`bench/score.py`. What holds the score down is policy shape: how eagerly the
trigger is pulled, how much slack the crosshair gets, and how often a decision is
made. This sweeps those and reports what actually moves the score.

Episodes run in **real time**, deliberately, even though synchronous mode is twice
as fast to sweep. Measured on the same seed, synchronous mode scored +13 with 14
kills against real time's +1 with 2 kills, because pausing the world while the
model thinks hands it unlimited deliberation time and removes every consequence of
latency. Tuning there would optimise for a regime the demo does not run in.

    uv run python bench/tune.py                 # staged sweeps
    uv run python bench/tune.py --episodes 12
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom.baselines import RandomClient, ScriptedClient  # noqa: E402
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.game import make_game  # noqa: E402
from laya_doom.loop import DECISION_INTERVAL_TICS, MS_PER_TIC, DecisionLoop  # noqa: E402
from laya_doom.questions import BATTERY, FIRE_QUESTION, TURN_VARIANTS  # noqa: E402

RESULTS = Path(__file__).parent / "tuning.md"


@dataclass
class Config:
    name: str
    policy: str = "laya"
    fire_threshold: float = 0.5
    tolerance_px: int = 0
    interval_tics: int = DECISION_INTERVAL_TICS
    turn_variant: str = "scan"
    real_time: bool = True

    def battery(self) -> dict:
        return {"fire": FIRE_QUESTION, "turn": copy.deepcopy(TURN_VARIANTS[self.turn_variant])}


@dataclass
class Outcome:
    config: Config
    scores: list[float] = field(default_factory=list)
    kills: list[float] = field(default_factory=list)
    fire_rate: float = 0.0
    turns: Counter = field(default_factory=Counter)
    latencies: list[float] = field(default_factory=list)

    @property
    def mean_score(self) -> float:
        return statistics.mean(self.scores) if self.scores else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.scores) if len(self.scores) > 1 else 0.0

    @property
    def mean_kills(self) -> float:
        return statistics.mean(self.kills) if self.kills else 0.0

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies) if self.latencies else 0.0


def build_client(policy: str, url: str):
    if policy == "scripted":
        return ScriptedClient()
    if policy == "random":
        return RandomClient()
    return LayaMpsClient(url)


def evaluate(config: Config, episodes: int, seed: int, url: str) -> Outcome:
    client = build_client(config.policy, url)
    outcome = Outcome(config=config)
    fires = decisions = 0

    for episode in range(episodes):
        game = make_game(seed=seed + episode)
        loop = DecisionLoop(
            game, client, config.battery(),
            interval_ms=config.interval_tics * MS_PER_TIC,
            fire_threshold=config.fire_threshold,
            crosshair_tolerance_px=config.tolerance_px,
            real_time=config.real_time,
        )

        def on_tick(record):
            nonlocal fires, decisions
            if record.fresh and record.decision is not None:
                decisions += 1
                fire = record.decision.get("fire")
                turn = record.decision.get("turn")
                if fire is not None and float(fire.value) >= config.fire_threshold:
                    fires += 1
                if turn is not None:
                    outcome.turns[str(turn.value)] += 1
                outcome.latencies.append(record.decision.latency_ms)

        try:
            result = loop.run_episode(on_tick=on_tick)
        finally:
            loop.close()
            game.close()
        outcome.scores.append(result.score)
        outcome.kills.append(result.killcount)
        print(f"    {config.name}: episode {episode + 1}/{episodes} "
              f"score={result.score:+.0f} kills={result.killcount:.0f} "
              f"skipped={result.skipped_slots}", flush=True)

    client.close()
    outcome.fire_rate = fires / decisions if decisions else 0.0
    share = sum(outcome.turns.values()) or 1
    print(f"  {config.name:26s} score={outcome.mean_score:+.2f} (sd {outcome.stdev:.2f}) "
          f"kills={outcome.mean_kills:.1f} fire={outcome.fire_rate:.0%} "
          f"turns={ {k: round(v / share, 2) for k, v in outcome.turns.most_common()} }", flush=True)
    return outcome


def stages() -> dict[str, list[Config]]:
    """One lever at a time -- a full grid would be slower and harder to read."""
    return {
        "baselines": [
            Config("scripted", policy="scripted"),
            Config("random", policy="random"),
        ],
        "turn question": [
            Config("turn=criteria_led (waits)", turn_variant="criteria_led"),
            Config("turn=scan (searches)", turn_variant="scan"),
        ],
        "fire threshold": [
            Config("fire>=0.50", fire_threshold=0.50),
            Config("fire>=0.35", fire_threshold=0.35),
            Config("fire>=0.25", fire_threshold=0.25),
        ],
        "crosshair tolerance": [
            Config("tolerance=0px", tolerance_px=0),
            Config("tolerance=6px", tolerance_px=6),
            Config("tolerance=14px", tolerance_px=14),
        ],
        "cadence": [
            Config("3 tics (85ms)", interval_tics=3),
            Config("4 tics (114ms)", interval_tics=4),
            Config("6 tics (171ms)", interval_tics=6),
        ],
    }


def write_report(all_outcomes: dict[str, list[Outcome]], episodes: int) -> None:
    lines = [
        "# Tuning",
        "",
        f"`bench/tune.py`, {episodes} episodes per configuration, fixed seeds, "
        "`defend_the_center`.",
        "",
        "Episodes run in synchronous fast mode so the game waits for each decision:",
        "no skipped slots, no stale replies, policy quality isolated from latency.",
        "Scores in `defend_the_center` are +1 per kill and -1 for dying, so the spread",
        "between configurations is small in absolute terms and the standard deviation",
        "across episodes is large. Treat anything inside one standard deviation as noise.",
        "",
    ]
    for stage, outcomes in all_outcomes.items():
        lines += [
            f"## {stage}",
            "",
            "| configuration | mean score | sd | kills | fire rate | p50 ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for outcome in outcomes:
            lines.append(
                f"| `{outcome.config.name}` | **{outcome.mean_score:+.2f}** | {outcome.stdev:.2f} "
                f"| {outcome.mean_kills:.1f} | {outcome.fire_rate:.0%} | {outcome.p50:.0f} |"
            )
        lines.append("")
    RESULTS.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {RESULTS}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=6)
    parser.add_argument("--seed", type=int, default=2000)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--stage", action="append", help="limit to named stages")
    args = parser.parse_args()

    planned = stages()
    if args.stage:
        planned = {name: configs for name, configs in planned.items() if name in args.stage}

    all_outcomes: dict[str, list[Outcome]] = {}
    raw = {}
    for stage, configs in planned.items():
        print(f"\n{stage}:", flush=True)
        all_outcomes[stage] = [evaluate(config, args.episodes, args.seed, args.url) for config in configs]
        raw[stage] = [
            {"name": o.config.name, "mean_score": o.mean_score, "sd": o.stdev,
             "kills": o.mean_kills, "fire_rate": o.fire_rate, "scores": o.scores}
            for o in all_outcomes[stage]
        ]

    write_report(all_outcomes, args.episodes)
    (Path(__file__).parent / "tuning.json").write_text(json.dumps(raw, indent=1))


if __name__ == "__main__":
    main()
