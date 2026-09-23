"""Eval loop over deathmatch prompt variants.

Every large movement in this project has come from a question or state change, and
the offline fixture oracle has been wrong about which change helps more than once
-- so variants are judged by episode score, in lockstep, against the same scripted
baseline the gate uses.

Runs the cross product of move-question and weapon-question variants. Reports the
answer distribution alongside the score, because the distribution has diagnosed
every failure here faster than the score did: `advance` at 0%, `keep` at 2%,
`aim_left`/`aim_right` at 45%/45%.

    uv run python bench/prompts.py --episodes 4
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom import scenarios  # noqa: E402
from laya_doom.baselines import DeathmatchScriptedClient  # noqa: E402
from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.questions import (  # noqa: E402
    DEATHMATCH_MOVE_VARIANTS,
    DEATHMATCH_WEAPON_VARIANTS,
    FIRE_QUESTION,
)

from gate import run  # noqa: E402

RESULTS = Path(__file__).parent / "prompts.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=4)
    parser.add_argument("--seed", type=int, default=8200)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--harvest", type=Path)
    parser.add_argument("--baseline", action="store_true", help="also run the scripted policy")
    args = parser.parse_args()

    scenario = scenarios.DEATHMATCH
    results = []

    if args.baseline:
        scripted = DeathmatchScriptedClient()
        results.append(run("scripted", scripted, scenario, args.episodes, args.seed))
        scripted.close()

    harvested: list = [] if args.harvest else None
    client = LayaMpsClient(args.url)
    for move_name, weapon_name in itertools.product(DEATHMATCH_MOVE_VARIANTS, DEATHMATCH_WEAPON_VARIANTS):
        battery = {
            "fire": FIRE_QUESTION,
            "move": DEATHMATCH_MOVE_VARIANTS[move_name],
            "weapon": DEATHMATCH_WEAPON_VARIANTS[weapon_name],
        }
        label = f"move={move_name}/weapon={weapon_name}"
        # Each variant gets its own scenario object so the battery is what changes.
        variant = scenarios.Scenario(
            name=scenario.name, battery=battery, interval_tics=scenario.interval_tics,
            game_variables=scenario.game_variables, extra_buttons=scenario.extra_buttons,
            goal_x=scenario.goal_x, notes=scenario.notes,
        )
        results.append(run(label, client, variant, args.episodes, args.seed, record=harvested))
    client.close()

    if args.harvest and harvested:
        args.harvest.parent.mkdir(parents=True, exist_ok=True)
        with args.harvest.open("a") as sink:
            for row in harvested:
                sink.write(json.dumps(row) + "\n")
        print(f"\nappended {len(harvested)} rows -> {args.harvest}")

    ranked = sorted(results, key=lambda r: -r["mean_score"])
    lines = [
        "# deathmatch prompt eval",
        "",
        f"`bench/prompts.py`, {args.episodes} episodes per variant, lockstep, seed {args.seed}.",
        "Bounded commitments are active: an aim holds 4 tics, a sweep 12, a weapon 20,",
        "and only a more urgent action interrupts one.",
        "",
        "| variant | mean score | sd | kills | p50 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for r in ranked:
        lines.append(f"| `{r['name']}` | **{r['mean_score']:+.2f}** | {r['sd']:.2f} "
                     f"| {r['mean_kills']:.1f} | {r['p50_ms']:.0f} ms |")
    lines += ["", "## Answer distributions", ""]
    for r in ranked:
        lines.append(f"- `{r['name']}`: {r['answers']}")
    RESULTS.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {RESULTS}")
    for r in ranked:
        print(f"  {r['name']:34s} {r['mean_score']:+7.2f} (sd {r['sd']:5.2f})  {r['answers']}")


if __name__ == "__main__":
    main()
