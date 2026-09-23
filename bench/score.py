"""Score candidate question schemas against labelled fixture states.

Why a bench exists at all: discovery showed the same `turn` question scoring
confidence 0.0115 (and wrong) on one state phrasing and 0.228 (and correct) on
another. Schema selection is therefore an experiment, not a preference.

The oracle is mechanically derivable from the observation, which is the honest
tension in this whole demo: Python *can* compute the right action. The bench
measures whether LAYA recovers that action from prose alone -- the demo's claim
is about the model class holding a real-time loop, never about it being the only
way to aim a gun.

Each question is formatted and batched independently by the server, so asking
all candidate variants in one request is equivalent to asking them separately,
and much faster.

    uv run python bench/score.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom.client import LayaMpsClient  # noqa: E402
from laya_doom.questions import FIRE_VARIANTS, THREAT, TURN_VARIANTS  # noqa: E402
from laya_doom.state import FAR, Observation, from_fixture, plain_name, serialize  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS = Path(__file__).parent / "results.md"
HALF_FOV_DEGREES = 45.0  # Doom's default field of view is 90 degrees


# --- ground truth ----------------------------------------------------------

def oracle(observation: Observation) -> dict:
    """The correct action, derived from the observation.

    With nothing visible the right answer is to search; aimed at something distant,
    to close the distance. Variants are scored only against options they actually
    offer -- a question with no `scan` or `advance` option falls back to `hold`
    rather than being marked wrong for a choice it was never given.
    """
    if observation.nearest is None:
        turn = "scan"
    elif observation.nearest.in_crosshair:
        # Aimed: close the distance on a long shot, otherwise stand and shoot.
        turn = "advance" if observation.nearest.distance_phrase == FAR else "hold"
    else:
        turn = observation.nearest.side
    return {
        "fire": observation.crosshair_target is not None and observation.ammo > 0,
        "turn": turn,
    }


def _expected_for(wanted: str, offered: set[str]) -> str:
    """Fall back to the best option a variant actually offers."""
    return wanted if wanted in offered else "hold"


def situation(observation: Observation) -> str:
    """Coverage bucket, so the fixture set is not all one kind of tick."""
    if observation.ammo <= 0:
        return "out of ammo"
    if observation.health <= 30:
        return "low health"
    if observation.nearest is None:
        return "no enemy"
    if len(observation.enemies) > 1:
        return "multiple enemies"
    if observation.nearest.in_crosshair:
        return "enemy centred"
    return f"enemy {observation.nearest.side}"


# --- state renderers -------------------------------------------------------

def prose_state(observation: Observation) -> dict:
    """What the project ships."""
    return serialize(observation)


def degrees_state(observation: Observation) -> dict:
    """The phrasing discovery showed failing, kept as a control.

    Reproduces the original probe: bearing in degrees, distance in world units,
    no plain-language spatial relation. If prose does not beat this, the whole
    premise of state.py is wrong and should be abandoned rather than defended.
    """
    nearest = observation.nearest
    if nearest is None:
        return {"health": int(observation.health), "ammo": int(observation.ammo), "enemies_visible": 0}
    degrees = nearest.offset_fraction * HALF_FOV_DEGREES
    return {
        "health": int(observation.health),
        "ammo": int(observation.ammo),
        "enemies_visible": len(observation.enemies),
        "nearest_enemy": (
            f"{plain_name(nearest.name)}, bearing {degrees:+.0f} degrees, "
            f"distance {nearest.distance:.0f}, "
            f"{'in crosshair' if nearest.in_crosshair else 'not in crosshair'}"
        ),
    }


RENDERERS = {"prose": prose_state, "degrees": degrees_state}


# --- fixture selection -----------------------------------------------------

def load_states(per_situation: int) -> list[Observation]:
    """A spread of real ticks, plus synthesised health/ammo edge cases."""
    buckets: dict[str, list[Observation]] = {}
    for path in sorted(FIXTURES.glob("*.json")):
        for fixture in json.loads(path.read_text()):
            observation = from_fixture(fixture)
            bucket = buckets.setdefault(situation(observation), [])
            if len(bucket) < per_situation:
                bucket.append(observation)

    # Captured play never drops the player below 30 health or empties the clip,
    # so those two situations are synthesised from real geometry.
    engaged = next(
        (o for o in buckets.get("enemy centred", []) + buckets.get("enemy left", []) if o.nearest),
        None,
    )
    if engaged is not None:
        buckets.setdefault("low health", []).append(replace(engaged, health=12.0))
        buckets.setdefault("out of ammo", []).append(replace(engaged, ammo=0.0))

    states = [observation for bucket in buckets.values() for observation in bucket]
    print(f"{len(states)} states across {len(buckets)} situations: "
          + ", ".join(f"{name} x{len(bucket)}" for name, bucket in sorted(buckets.items())))
    return states


# --- scoring ---------------------------------------------------------------

def run(client: LayaMpsClient, states: list[Observation]) -> dict:
    questions = {f"fire_{name}": question for name, question in FIRE_VARIANTS.items()}
    questions |= {f"turn_{name}": question for name, question in TURN_VARIANTS.items()}
    questions["threat"] = THREAT

    records = []
    for index, observation in enumerate(states, 1):
        truth = situation(observation)
        expected = oracle(observation)
        for style, render in RENDERERS.items():
            decision = client.decide(render(observation), questions)
            records.append({
                "style": style,
                "situation": truth,
                "health": observation.health,
                "expected": expected,
                "latency_ms": decision.latency_ms,
                "answers": {
                    name: {
                        "value": answer.value,
                        "confidence": answer.confidence,
                        "top_probability": answer.top_probability,
                    }
                    for name, answer in decision.answers.items()
                },
            })
        print(f"\r  {index}/{len(states)} states", end="", flush=True)
    print()
    return {"records": records}


def summarise(records: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for style in RENDERERS:
        rows = [record for record in records if record["style"] == style]
        if not rows:
            continue
        stats: dict[str, dict] = {}
        for name in FIRE_VARIANTS:
            key = f"fire_{name}"
            correct = [
                (row["answers"][key]["value"] >= 0.5) == row["expected"]["fire"] for row in rows
            ]
            stats[key] = {
                "accuracy": statistics.mean(correct),
                "mean_confidence": statistics.mean(row["answers"][key]["confidence"] for row in rows),
            }
        for name, question in TURN_VARIANTS.items():
            key = f"turn_{name}"
            offered = set(question["criteria"])
            correct = [
                row["answers"][key]["value"] == _expected_for(row["expected"]["turn"], offered)
                for row in rows
            ]
            stats[key] = {
                "accuracy": statistics.mean(correct),
                "mean_confidence": statistics.mean(row["answers"][key]["confidence"] for row in rows),
            }
        # Threat has no crisp oracle. Check it responds to health at all.
        hurt = [row["answers"]["threat"]["value"] for row in rows if row["health"] <= 30]
        healthy = [row["answers"]["threat"]["value"] for row in rows if row["health"] > 30]
        stats["threat"] = {
            "mean_when_hurt": statistics.mean(hurt) if hurt else None,
            "mean_when_healthy": statistics.mean(healthy) if healthy else None,
            "mean_confidence": statistics.mean(row["answers"]["threat"]["confidence"] for row in rows),
        }
        latencies = sorted(row["latency_ms"] for row in rows)
        summary[style] = {
            "questions": stats,
            "latency_p50_ms": statistics.median(latencies),
            "samples": len(rows),
        }
    return summary


def per_situation_accuracy(records: list[dict], style: str, key: str, field: str) -> dict[str, float]:
    buckets: dict[str, list[bool]] = {}
    for record in records:
        if record["style"] != style:
            continue
        answer = record["answers"][key]["value"]
        if field == "fire":
            correct = (answer >= 0.5) == record["expected"][field]
        else:
            offered = set(TURN_VARIANTS[key.removeprefix("turn_")]["criteria"])
            correct = answer == _expected_for(record["expected"]["turn"], offered)
        buckets.setdefault(record["situation"], []).append(correct)
    return {name: statistics.mean(values) for name, values in sorted(buckets.items())}


def write_report(summary: dict, records: list[dict]) -> None:
    lines = [
        "# Question schema bench",
        "",
        "Generated by `bench/score.py`. Accuracy is against a mechanically derived oracle;",
        "`prose` is the shipped state renderer, `degrees` is the phrasing discovery showed",
        "failing, kept as a control.",
        "",
        f"States per style: {summary[next(iter(summary))]['samples']}.",
        "",
        "## Accuracy by state renderer",
        "",
        "| Question | prose accuracy | prose confidence | degrees accuracy | degrees confidence |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key in list(FIRE_VARIANTS and [f"fire_{n}" for n in FIRE_VARIANTS]) + [f"turn_{n}" for n in TURN_VARIANTS]:
        prose = summary["prose"]["questions"][key]
        degrees = summary["degrees"]["questions"][key]
        lines.append(
            f"| `{key}` | {prose['accuracy']:.0%} | {prose['mean_confidence']:.3f} "
            f"| {degrees['accuracy']:.0%} | {degrees['mean_confidence']:.3f} |"
        )
    lines += ["", "## Threat, which has no crisp oracle", ""]
    for style in summary:
        threat = summary[style]["questions"]["threat"]
        hurt = threat["mean_when_hurt"]
        healthy = threat["mean_when_healthy"]
        lines.append(
            f"- `{style}`: mean score {hurt if hurt is None else f'{hurt:.2f}'} when hurt vs "
            f"{healthy if healthy is None else f'{healthy:.2f}'} when healthy "
            f"(confidence {threat['mean_confidence']:.3f})"
        )
    best_turn = max(TURN_VARIANTS, key=lambda n: summary["prose"]["questions"][f"turn_{n}"]["accuracy"])
    best_fire = max(FIRE_VARIANTS, key=lambda n: summary["prose"]["questions"][f"fire_{n}"]["accuracy"])
    lines += [
        "",
        "## Per-situation accuracy for the winning variants",
        "",
        f"`fire_{best_fire}`:",
        "",
    ]
    for name, accuracy in per_situation_accuracy(records, "prose", f"fire_{best_fire}", "fire").items():
        lines.append(f"- {name}: {accuracy:.0%}")
    lines += ["", f"`turn_{best_turn}`:", ""]
    for name, accuracy in per_situation_accuracy(records, "prose", f"turn_{best_turn}", "turn").items():
        lines.append(f"- {name}: {accuracy:.0%}")
    lines += [
        "",
        "## Outcome",
        "",
        f"- Winning fire variant: **`{best_fire}`** "
        f"({summary['prose']['questions'][f'fire_{best_fire}']['accuracy']:.0%})",
        f"- Winning turn variant: **`{best_turn}`** "
        f"({summary['prose']['questions'][f'turn_{best_turn}']['accuracy']:.0%})",
        "",
    ]
    RESULTS.write_text("\n".join(lines) + "\n")
    print(f"wrote {RESULTS}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-situation", type=int, default=6)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--raw", type=Path, default=Path(__file__).parent / "results.json")
    args = parser.parse_args()

    states = load_states(args.per_situation)
    client = LayaMpsClient(args.url)
    warm = {"fire": FIRE_VARIANTS["statement"]}
    for _ in range(2):  # first call was 686 ms cold; never let warmup pollute the numbers
        client.decide(prose_state(states[0]), warm)

    result = run(client, states)
    client.close()

    summary = summarise(result["records"])
    args.raw.write_text(json.dumps({"summary": summary, **result}, indent=1, default=str))
    write_report(summary, result["records"])

    for style, block in summary.items():
        print(f"\n{style}: p50 {block['latency_p50_ms']:.1f} ms over {block['samples']} states")
        for key, stats in block["questions"].items():
            if "accuracy" in stats:
                print(f"  {key:22s} acc={stats['accuracy']:.0%}  conf={stats['mean_confidence']:.3f}")


if __name__ == "__main__":
    main()
