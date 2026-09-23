"""One seam between the game loop and LAYA.

Two backends answer the same questions and are normalised to one shape here:

* ``LayaMpsClient``  -- the MPS-optimised local server (``afshinm/laya-mps``), the default.
* ``InProcessClient`` -- upstream ``laya.load()`` in this process, a fallback.

They disagree in ways that would otherwise leak into the loop and the UI:

==================  =========================  ============================
field               laya-mps                   upstream laya 0.3.6
==================  =========================  ============================
score levels (in)   ``levels``: list           ``criteria``: list
score probs (out)   list, positional           dict keyed by index string
noul (out)          ``{"noul": P(true)}``      also carries ``confidence``
==================  =========================  ============================

``noul`` polarity is the one detail worth stating twice: upstream Laya orders the
labels ``[false, true]`` and laya-mps reverses them before formatting, so the
``noul`` float is **P(true)** on both paths. Getting it backwards inverts the
trigger, and an inverted trigger is nearly impossible to spot from gameplay
alone -- ``tests/test_client.py`` pins it.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

QuestionType = Literal["choice", "score", "noul"]


class DecisionError(RuntimeError):
    """The backend could not be reached, or answered with something unusable."""


@dataclass(frozen=True)
class Answer:
    """One typed answer, with the whole distribution kept for display.

    ``value`` is the chosen label for ``choice``, the expected level for
    ``score``, and P(true) for ``noul``.
    """

    name: str
    type: QuestionType
    value: str | float
    distribution: dict[str, float]
    confidence: float

    @property
    def label(self) -> str:
        """A short human-readable rendering of the answer."""
        if self.type == "choice":
            return str(self.value)
        if self.type == "noul":
            return f"yes ({self.value:.0%})" if self.value >= 0.5 else f"no ({1 - self.value:.0%})"
        return f"{self.value:.2f}"

    @property
    def top_probability(self) -> float:
        """Probability mass on the reported answer."""
        if self.type == "noul":
            return max(float(self.value), 1.0 - float(self.value))
        return max(self.distribution.values()) if self.distribution else 0.0


@dataclass(frozen=True)
class Decision:
    """Every answer for one tick, plus how long it took to get them."""

    answers: dict[str, Answer]
    latency_ms: float
    server_ms: float | None = None
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def __getitem__(self, name: str) -> Answer:
        return self.answers[name]

    def get(self, name: str) -> Answer | None:
        return self.answers.get(name)


class DecisionClient(Protocol):
    """What the loop needs from a decision backend."""

    def decide(self, state: Any, questions: dict[str, dict]) -> Decision: ...

    def close(self) -> None: ...


def _negentropy_confidence(probabilities: list[float]) -> float:
    """Normalised negentropy, matching laya-mps's own confidence formula.

    1.0 is a point mass, 0.0 is uniform. Recomputed rather than taken from the
    backend so that a ``noul`` answer -- which laya-mps reports without a
    confidence -- is scored on the same scale as everything else.
    """
    positive = [p for p in probabilities if p > 0]
    if len(probabilities) < 2 or not positive:
        return 0.0
    entropy_term = sum(p * math.log(p) for p in positive)
    return min(1.0, max(0.0, 1 + entropy_term / math.log(len(probabilities))))


def _normalise_answer(name: str, question: dict, payload: dict) -> Answer:
    """Turn either backend's answer payload into an ``Answer``."""
    kind = payload.get("type") or question.get("type")

    if kind == "choice":
        probabilities = {str(k): float(v) for k, v in (payload.get("probabilities") or {}).items()}
        choice = payload.get("choice")
        if choice is None:
            raise DecisionError(f"question {name!r}: choice answer without a choice")
        if choice not in question.get("criteria", {}):
            raise DecisionError(f"question {name!r}: {choice!r} is not one of the offered options")
        return Answer(
            name=name,
            type="choice",
            value=str(choice),
            distribution=probabilities,
            confidence=float(payload.get("confidence", _negentropy_confidence(list(probabilities.values())))),
        )

    if kind == "score":
        levels = _score_levels(question)
        raw_probabilities = payload.get("probabilities") or []
        # laya-mps returns a positional list; upstream returns a dict keyed by index.
        if isinstance(raw_probabilities, dict):
            ordered = [float(raw_probabilities[k]) for k in sorted(raw_probabilities, key=lambda k: int(k))]
        else:
            ordered = [float(p) for p in raw_probabilities]
        names = levels if len(levels) == len(ordered) else [str(i) for i in range(len(ordered))]
        return Answer(
            name=name,
            type="score",
            value=float(payload.get("score", 0.0)),
            distribution=dict(zip(names, ordered)),
            confidence=float(payload.get("confidence", _negentropy_confidence(ordered))),
        )

    if kind == "noul":
        if "noul" not in payload:
            raise DecisionError(f"question {name!r}: noul answer without a noul field")
        probability_true = float(payload["noul"])  # P(true) on both backends -- see module docstring
        distribution = {"true": probability_true, "false": 1.0 - probability_true}
        return Answer(
            name=name,
            type="noul",
            value=probability_true,
            distribution=distribution,
            confidence=_negentropy_confidence([probability_true, 1.0 - probability_true]),
        )

    raise DecisionError(f"question {name!r}: unknown answer type {kind!r}")


def _score_levels(question: dict) -> list[str]:
    """Level names for a score question, under either backend's spelling."""
    return [str(level) for level in (question.get("levels") or question.get("criteria") or [])]


def _normalise_response(questions: dict[str, dict], body: dict, latency_ms: float) -> Decision:
    answers_payload = body.get("answers")
    if not isinstance(answers_payload, dict):
        raise DecisionError("response contained no answers")
    missing = set(questions) - set(answers_payload)
    if missing:
        raise DecisionError(f"backend skipped questions: {sorted(missing)}")
    answers = {
        name: _normalise_answer(name, questions[name], answers_payload[name]) for name in questions
    }
    metrics = body.get("metrics") or {}
    server_ms = metrics.get("request_ms")
    return Decision(
        answers=answers,
        latency_ms=latency_ms,
        server_ms=float(server_ms) if server_ms is not None else None,
        model=str(body.get("model", "")),
        raw=body,
    )


class LayaMpsClient:
    """Talks to a running ``laya-mps`` server over loopback HTTP.

    The server accepts one request at a time (``max_active_requests: 1``), which
    suits the loop: it never has more than one decision outstanding anyway. The
    connection is pooled because at 10 requests/sec a fresh TCP handshake per
    call is pure overhead.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        timeout: float = 10.0,
        include_metrics: bool = True,
        busy_retries: int = 3,
        busy_backoff_ms: float = 40.0,
    ) -> None:
        import httpx

        self.base_url = base_url.rstrip("/")
        self._include_metrics = include_metrics
        # The server answers one request at a time and returns 503 while busy.
        # A second client -- play.py alongside the web app, say -- would otherwise
        # fail its warmup outright, which is a confusing way to learn that.
        self._busy_retries = busy_retries
        self._busy_backoff_ms = busy_backoff_ms
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    def config(self) -> dict:
        """Server settings, including the memory mode and question batch size."""
        return self._request("GET", "/v1/config")

    def health(self) -> dict:
        return self._request("GET", "/health")

    def decide(self, state: Any, questions: dict[str, dict]) -> Decision:
        payload = {"state": state, "questions": questions}
        started = time.perf_counter()
        body = self._request(
            "POST",
            "/v1/decisions",
            json=payload,
            params={"metrics": "true"} if self._include_metrics else None,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        return _normalise_response(questions, body, latency_ms)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        import time

        import httpx

        for attempt in range(self._busy_retries + 1):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.ConnectError as exc:
                raise DecisionError(
                    f"no laya-mps server at {self.base_url}. Start one with "
                    "`./scripts/serve.sh --memory full --question-batch-size 4` "
                    "in your laya-mps checkout."
                ) from exc
            except httpx.TimeoutException as exc:
                raise DecisionError(f"laya-mps timed out after {self._http.timeout}") from exc

            if response.status_code == 503 and attempt < self._busy_retries:
                # Another client holds the single inference slot. Wait and retry.
                time.sleep(self._busy_backoff_ms / 1000)
                continue
            if response.status_code == 503:
                raise DecisionError(
                    "laya-mps is busy with another client's inference. It serves one request at "
                    "a time -- stop the other run (the web app or play.py) and retry."
                )
            if response.status_code >= 400:
                raise DecisionError(f"laya-mps returned {response.status_code}: {response.text[:400]}")
            return response.json()
        raise DecisionError("laya-mps stayed busy across every retry")

    def close(self) -> None:
        self._http.close()


class InProcessClient:
    """Upstream ``laya`` loaded into this process. Fallback, not the default.

    Measured at p50 58.6 ms on CPU for three questions during discovery, against
    laya-mps's ~32 ms, and it puts torch in the game loop's address space. It
    exists so a broken server never blocks work.
    """

    def __init__(self, model_id: str = "convaiinnovations/laya", device: str | None = None) -> None:
        import os

        os.environ.setdefault("USE_TF", "0")  # transformers otherwise probes for TensorFlow and hangs
        import laya

        self._agent = laya.load(model_id, device=device)

    def decide(self, state: Any, questions: dict[str, dict]) -> Decision:
        started = time.perf_counter()
        body = self._agent.predict(state, self._to_upstream_dialect(questions))
        latency_ms = (time.perf_counter() - started) * 1000
        return _normalise_response(questions, body, latency_ms)

    @staticmethod
    def _to_upstream_dialect(questions: dict[str, dict]) -> dict[str, dict]:
        """Upstream spells a score question's levels ``criteria``; laya-mps says ``levels``."""
        translated: dict[str, dict] = {}
        for name, question in questions.items():
            if question.get("type") == "score" and "levels" in question:
                question = {**question, "criteria": question["levels"]}
                question.pop("levels", None)
            translated[name] = question
        return translated

    def close(self) -> None:  # nothing to release
        return None


class StubClient:
    """Fixed answers, no model. For loop tests and for isolating loop bugs.

    ``delay_ms`` fakes a slow backend, which is how the latch and the
    generation guard get exercised without waiting on real inference.
    """

    def __init__(self, answers: dict[str, Any], *, delay_ms: float = 0.0) -> None:
        self._answers = answers
        self._delay_ms = delay_ms
        self.calls = 0

    def decide(self, state: Any, questions: dict[str, dict]) -> Decision:
        self.calls += 1
        started = time.perf_counter()
        if self._delay_ms:
            time.sleep(self._delay_ms / 1000)
        answers = {}
        for name, question in questions.items():
            answers[name] = self._stub_answer(name, question)
        return Decision(
            answers=answers,
            latency_ms=(time.perf_counter() - started) * 1000,
            model="stub",
        )

    def _stub_answer(self, name: str, question: dict) -> Answer:
        wanted = self._answers.get(name)
        kind = question["type"]
        if kind == "choice":
            options = list(question["criteria"])
            chosen = wanted if wanted in options else options[0]
            distribution = {option: (0.9 if option == chosen else 0.1 / max(1, len(options) - 1)) for option in options}
            return Answer(name, "choice", chosen, distribution, _negentropy_confidence(list(distribution.values())))
        if kind == "noul":
            probability = float(wanted) if isinstance(wanted, (int, float)) else 1.0 if wanted else 0.0
            return Answer(name, "noul", probability, {"true": probability, "false": 1 - probability},
                          _negentropy_confidence([probability, 1 - probability]))
        levels = _score_levels(question)
        value = float(wanted) if isinstance(wanted, (int, float)) else 0.0
        distribution = {level: 1.0 / len(levels) for level in levels} if levels else {}
        return Answer(name, "score", value, distribution, _negentropy_confidence(list(distribution.values())))

    def close(self) -> None:
        return None
