"""Pins the backend details that fail silently if wrong."""

from __future__ import annotations

import math

import pytest

from laya_doom.client import (
    Answer,
    DecisionError,
    InProcessClient,
    StubClient,
    _negentropy_confidence,
    _normalise_answer,
    _normalise_response,
)

FIRE = {"type": "noul", "instructions": "An enemy is lined up in the crosshair right now."}
TURN = {
    "type": "choice",
    "instructions": "Aim at the enemy.",
    "criteria": {"left": "Turn left", "right": "Turn right", "hold": "Do not turn"},
}
THREAT = {"type": "score", "instructions": "How much danger?", "levels": ["safe", "threatened", "about to die"]}


class TestNoulPolarity:
    """``noul`` is P(true) on both backends.

    Upstream Laya orders labels ``[false, true]``; laya-mps reverses them before
    formatting so index 0 is "true". If this inverts, the trigger fires exactly
    when it should not -- and gameplay alone will not reveal which way round it is.
    """

    def test_high_noul_means_true(self):
        answer = _normalise_answer("fire", FIRE, {"type": "noul", "noul": 0.93})
        assert answer.value == pytest.approx(0.93)
        assert answer.distribution["true"] == pytest.approx(0.93)
        assert answer.distribution["false"] == pytest.approx(0.07)
        assert answer.label.startswith("yes")

    def test_low_noul_means_false(self):
        answer = _normalise_answer("fire", FIRE, {"type": "noul", "noul": 0.04})
        assert answer.distribution["false"] == pytest.approx(0.96)
        assert answer.label.startswith("no")

    def test_distribution_sums_to_one(self):
        answer = _normalise_answer("fire", FIRE, {"type": "noul", "noul": 0.37})
        assert sum(answer.distribution.values()) == pytest.approx(1.0)


class TestScoreShapeDivergence:
    """laya-mps returns positional probabilities; upstream returns a dict keyed by index."""

    def test_laya_mps_positional_list(self):
        answer = _normalise_answer(
            "threat", THREAT, {"type": "score", "score": 1.2, "probabilities": [0.1, 0.6, 0.3]}
        )
        assert answer.distribution == pytest.approx({"safe": 0.1, "threatened": 0.6, "about to die": 0.3})

    def test_upstream_index_keyed_dict(self):
        answer = _normalise_answer(
            "threat",
            THREAT,
            {"type": "score", "score": 1.2, "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3}},
        )
        assert answer.distribution == pytest.approx({"safe": 0.1, "threatened": 0.6, "about to die": 0.3})

    def test_both_shapes_agree(self):
        positional = _normalise_answer(
            "threat", THREAT, {"type": "score", "score": 1.2, "probabilities": [0.1, 0.6, 0.3]}
        )
        keyed = _normalise_answer(
            "threat", THREAT, {"type": "score", "score": 1.2, "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3}}
        )
        assert positional.distribution == pytest.approx(keyed.distribution)
        assert positional.confidence == pytest.approx(keyed.confidence)


class TestScoreDialect:
    """Upstream spells a score question's levels ``criteria``; laya-mps says ``levels``."""

    def test_levels_translated_for_upstream(self):
        translated = InProcessClient._to_upstream_dialect({"threat": THREAT, "turn": TURN})
        assert translated["threat"]["criteria"] == ["safe", "threatened", "about to die"]
        assert "levels" not in translated["threat"]
        # A choice question's criteria must survive untouched.
        assert translated["turn"]["criteria"] == TURN["criteria"]

    def test_translation_does_not_mutate_the_original(self):
        InProcessClient._to_upstream_dialect({"threat": THREAT})
        assert THREAT["levels"] == ["safe", "threatened", "about to die"]
        assert "criteria" not in THREAT


class TestChoiceAnswers:
    def test_choice_carries_full_distribution(self):
        answer = _normalise_answer(
            "turn",
            TURN,
            {"type": "choice", "choice": "left", "probabilities": {"left": 0.68, "right": 0.17, "hold": 0.15},
             "confidence": 0.228},
        )
        assert answer.value == "left"
        assert answer.top_probability == pytest.approx(0.68)
        assert len(answer.distribution) == 3

    def test_choice_outside_the_offered_options_is_rejected(self):
        with pytest.raises(DecisionError, match="not one of the offered options"):
            _normalise_answer("turn", TURN, {"type": "choice", "choice": "backwards", "probabilities": {}})


class TestConfidence:
    def test_point_mass_is_confident(self):
        assert _negentropy_confidence([1.0, 0.0]) == pytest.approx(1.0)

    def test_uniform_is_unconfident(self):
        assert _negentropy_confidence([1 / 3, 1 / 3, 1 / 3]) == pytest.approx(0.0, abs=1e-9)

    def test_near_uniform_is_low(self):
        # The distribution the probe actually returned for a badly-phrased turn question.
        assert _negentropy_confidence([0.2602, 0.3741, 0.3657]) < 0.05


class TestResponseNormalisation:
    def test_missing_question_is_an_error(self):
        with pytest.raises(DecisionError, match="skipped questions"):
            _normalise_response({"fire": FIRE, "turn": TURN}, {"answers": {"fire": {"type": "noul", "noul": 0.5}}}, 10.0)

    def test_no_answers_is_an_error(self):
        with pytest.raises(DecisionError, match="no answers"):
            _normalise_response({"fire": FIRE}, {"model": "x"}, 10.0)

    def test_server_metrics_are_kept_separate_from_wall_clock(self):
        decision = _normalise_response(
            {"fire": FIRE},
            {"answers": {"fire": {"type": "noul", "noul": 0.5}}, "metrics": {"request_ms": 31.4}, "model": "m"},
            71.5,
        )
        assert decision.latency_ms == pytest.approx(71.5)
        assert decision.server_ms == pytest.approx(31.4)

    def test_absent_metrics_leave_server_ms_unset(self):
        decision = _normalise_response({"fire": FIRE}, {"answers": {"fire": {"type": "noul", "noul": 0.5}}}, 71.5)
        assert decision.server_ms is None


class TestStubClient:
    def test_returns_the_requested_answers(self):
        stub = StubClient({"fire": 0.9, "turn": "right", "threat": 1.5})
        decision = stub.decide({"observation": "x"}, {"fire": FIRE, "turn": TURN, "threat": THREAT})
        assert decision["fire"].value == pytest.approx(0.9)
        assert decision["turn"].value == "right"
        assert decision["threat"].value == pytest.approx(1.5)
        assert stub.calls == 1

    def test_delay_is_observable(self):
        stub = StubClient({"fire": 1.0}, delay_ms=25)
        assert stub.decide({}, {"fire": FIRE}).latency_ms >= 20
