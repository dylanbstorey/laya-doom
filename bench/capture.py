"""Record ViZDoom game states as JSON fixtures.

Fixtures let the serializer and the question bench run without a Doom process,
and keep the tests deterministic. Run with a scenario name; writes one JSON file
per captured tick into bench/fixtures/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from pathlib import Path

import vizdoom as vzd

FIXTURES = Path(__file__).parent / "fixtures"


def capture(scenario: str, ticks: int, seed: int, every: int) -> list[dict]:
    game = vzd.DoomGame()
    game.load_config(os.path.join(vzd.scenarios_path, f"{scenario}.cfg"))
    game.set_window_visible(False)
    game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    game.set_labels_buffer_enabled(True)
    game.set_seed(seed)
    game.init()

    buttons = game.get_available_buttons()
    rng = random.Random(seed)
    captured: list[dict] = []

    game.new_episode()
    for tick in range(ticks):
        if game.is_episode_finished():
            game.new_episode()
        state = game.get_state()
        if state is None:
            continue
        if tick % every == 0:
            captured.append(record(state, game, scenario, tick))
        action = [0] * len(buttons)
        # Wander so the fixtures cover varied bearings rather than one frozen pose.
        action[rng.randrange(len(buttons))] = 1
        game.make_action(action, 4)

    game.close()
    return captured


def record(state, game, scenario: str, tick: int) -> dict:
    variables = {
        str(name).split(".")[-1]: float(value)
        for name, value in zip(game.get_available_game_variables(), state.game_variables)
    }
    labels = [
        {
            "name": label.object_name,
            "x": float(label.object_position_x),
            "y": float(label.object_position_y),
            "z": float(label.object_position_z),
            "bbox": [int(label.x), int(label.y), int(label.width), int(label.height)],
        }
        for label in state.labels
    ]
    player = next((label for label in labels if label["name"] == "DoomPlayer"), None)
    for label in labels:
        if player and label is not player:
            label["distance"] = round(math.dist((label["x"], label["y"]), (player["x"], player["y"])), 1)
    return {
        "scenario": scenario,
        "tick": tick,
        "screen_width": game.get_screen_width(),
        "screen_height": game.get_screen_height(),
        "game_variables": variables,
        "labels": labels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="defend_the_center")
    parser.add_argument("--ticks", type=int, default=400)
    parser.add_argument("--every", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=FIXTURES)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    states = capture(args.scenario, args.ticks, args.seed, args.every)
    path = args.out / f"{args.scenario}.json"
    path.write_text(json.dumps(states, indent=1))

    distances = [
        label["distance"]
        for state in states
        for label in state["labels"]
        if "distance" in label and label["name"] != "DoomPlayer"
    ]
    print(f"wrote {len(states)} states to {path}")
    print(f"enemy sightings: {len(distances)}")
    if distances:
        distances.sort()
        marks = [0, 5, 10, 25, 50, 75, 90, 100]
        quantiles = {f"p{m}": round(distances[min(len(distances) - 1, m * len(distances) // 100)]) for m in marks}
        print("distance distribution:", quantiles)
    names = sorted({label["name"] for state in states for label in state["labels"]})
    print("object names seen:", names)


if __name__ == "__main__":
    main()
