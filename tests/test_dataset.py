"""Loading harvested decisions as a training set."""

from __future__ import annotations

import json

import numpy as np
import pytest

from laya_doom.dataset import Batch, describe, load
from laya_doom.features import FEATURE_NAMES

OPTIONS = ["advance", "hold", "aim_left", "scan"]


def row(episode: int, score: float, *, battery: str = "abc123", run: str = "r1",
        fire: float = 0.3, move: str = "hold", scenario: str = "deathmatch") -> dict:
    distribution = {name: (0.7 if name == move else 0.1) for name in OPTIONS}
    return {
        "features": [0.5] * len(FEATURE_NAMES),
        "answers": {
            "fire": {"type": "noul", "value": fire,
                     "distribution": {"true": fire, "false": 1 - fire}, "confidence": 0.5},
            "move": {"type": "choice", "value": move, "distribution": distribution, "confidence": 0.4},
        },
        "run": run, "episode": episode, "episode_score": score,
        "scenario": scenario, "battery": battery,
    }


def write(tmp_path, rows) -> object:
    path = tmp_path / "harvest.jsonl"
    with path.open("w") as sink:
        for r in rows:
            sink.write(json.dumps(r) + "\n")
    return path


class TestDescribe:
    def test_summarises_without_loading_targets(self, tmp_path):
        path = write(tmp_path, [row(0, 10.0), row(0, 10.0), row(1, 2.0)])
        summary = describe(path)
        assert summary["rows"] == 3
        assert summary["episodes"] == 2
        assert summary["best"] == 10.0 and summary["worst"] == 2.0

    def test_empty_file_is_not_an_error(self, tmp_path):
        assert describe(write(tmp_path, []))["rows"] == 0


class TestProvenance:
    def test_mixing_two_batteries_is_refused(self, tmp_path):
        """The prompts changed six times. Mixing policies would be silent corruption."""
        path = write(tmp_path, [row(0, 5.0, battery="aaa"), row(1, 5.0, battery="bbb")])
        with pytest.raises(ValueError, match="mixes 2 question batteries"):
            load(path)

    def test_one_battery_can_be_selected_from_a_mixed_file(self, tmp_path):
        path = write(tmp_path, [row(0, 5.0, battery="aaa"), row(1, 5.0, battery="bbb")])
        assert len(load(path, battery="aaa")) == 1

    def test_a_changed_feature_width_is_caught(self, tmp_path):
        bad = row(0, 5.0)
        bad["features"] = [0.1, 0.2]
        with pytest.raises(ValueError, match="features on disk"):
            load(write(tmp_path, [bad]))


class TestFiltering:
    def test_min_score_keeps_only_good_episodes(self, tmp_path):
        path = write(tmp_path, [row(0, 9.0), row(1, 1.0), row(2, 6.0)])
        assert len(load(path, min_score=5.0)) == 2

    def test_top_fraction_keeps_the_best_share(self, tmp_path):
        path = write(tmp_path, [row(i, float(i)) for i in range(10)])
        kept = load(path, top_fraction=0.3)
        assert len(kept) == 3
        assert kept.episode_scores.min() >= 7.0

    def test_an_empty_filter_result_is_an_error_not_a_crash(self, tmp_path):
        with pytest.raises(ValueError, match="kept nothing"):
            load(write(tmp_path, [row(0, 1.0)]), min_score=99.0)

    def test_scenario_filter(self, tmp_path):
        path = write(tmp_path, [row(0, 5.0), row(1, 5.0, scenario="deadly_corridor")])
        assert len(load(path, scenario="deathmatch")) == 1


class TestTargets:
    def test_soft_targets_are_kept_not_argmaxed(self, tmp_path):
        """The probabilities are the thing LAYA is good at. Measured on real data,
        `advance` carries 10% of the probability mass while winning 0% of argmaxes --
        hard labels would throw that away entirely."""
        batch = load(write(tmp_path, [row(0, 5.0, move="hold")]))
        assert batch.move.shape == (1, len(OPTIONS))
        assert batch.move.sum(axis=1)[0] == pytest.approx(1.0)
        assert (batch.move[0] > 0).all(), "every option keeps its share"

    def test_fire_is_the_probability_not_a_flag(self, tmp_path):
        batch = load(write(tmp_path, [row(0, 5.0, fire=0.37)]))
        assert batch.fire[0] == pytest.approx(0.37)

    def test_option_order_is_stable(self, tmp_path):
        batch = load(write(tmp_path, [row(0, 5.0), row(1, 5.0)]))
        assert batch.move_options == OPTIONS

    def test_score_weighting_favours_better_episodes_without_zeroing_any(self, tmp_path):
        path = write(tmp_path, [row(0, 10.0), row(1, 0.0)])
        batch = load(path, weight_by_score=True)
        assert batch.weights.min() > 0
        assert batch.weights[0] > batch.weights[1]


class TestSplitting:
    def test_split_is_by_episode_not_by_row(self, tmp_path):
        """Consecutive ticks are near-duplicates, so a row split would leak the
        training set into the test set and report a meaningless score."""
        rows = [row(episode, 5.0) for episode in range(10) for _ in range(20)]
        train, test = load(write(tmp_path, rows)).split(holdout=0.3, seed=0)
        assert set(train.episode_ids) & set(test.episode_ids) == set()
        assert len(train) + len(test) == 200

    def test_split_is_deterministic(self, tmp_path):
        rows = [row(episode, 5.0) for episode in range(8) for _ in range(5)]
        path = write(tmp_path, rows)
        first, _ = load(path).split(seed=3)
        second, _ = load(path).split(seed=3)
        assert np.array_equal(first.episode_ids, second.episode_ids)


class TestStudentRoundTrip:
    """A trained student must load and answer without torch."""

    def test_save_and_load_preserves_behaviour(self, tmp_path):
        from laya_doom.student import Student, new

        student = new(OPTIONS, hidden=16, seed=2)
        features = np.random.default_rng(0).random(len(FEATURE_NAMES)).astype(np.float32)
        before = student.forward(features)

        path = tmp_path / "s.npz"
        student.save(path)
        after = Student.load(path).forward(features)

        assert before[0] == pytest.approx(after[0])
        assert np.allclose(before[1], after[1])

    def test_move_distribution_is_a_distribution(self):
        from laya_doom.student import new

        student = new(OPTIONS, hidden=16, seed=1)
        _, move = student.forward(np.zeros(len(FEATURE_NAMES), dtype=np.float32))
        assert move.sum() == pytest.approx(1.0)
        assert (move >= 0).all()

    def test_client_answers_like_the_teacher(self):
        from laya_doom.student import StudentClient, new

        client = StudentClient(new(OPTIONS, hidden=16, seed=3))
        decision = client.decide({"enemies_in_sight": 0, "health": 100, "ammunition": 20}, {})
        assert decision["fire"].type == "noul"
        assert decision["move"].type == "choice"
        assert decision["move"].value in OPTIONS
        assert 0.0 <= decision["fire"].value <= 1.0

    def test_a_decision_is_far_faster_than_the_teacher(self):
        """The whole point: LAYA p50 is 127 ms, so the loop skips slots. A student
        has to be fast enough to decide every tic (28.6 ms) with room to spare."""
        from laya_doom.student import StudentClient, new

        client = StudentClient(new(OPTIONS, hidden=128, seed=4))
        state = {"enemies_in_sight": 1, "health": 80, "ammunition": 20,
                 "nearest_enemy": {"where": "to the left", "how_far": "close"}}
        client.decide(state, {})  # warm
        worst = max(client.decide(state, {}).latency_ms for _ in range(50))
        assert worst < 5.0, f"{worst:.2f} ms is too slow to decide every tic"
