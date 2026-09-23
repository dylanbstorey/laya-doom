"""Local web app: the Doom frame beside what LAYA was actually asked and answered.

A recording of Doom proves nothing. The demo is the frame *next to* the state
text, the typed answers, their probability distributions and the latency -- so a
viewer can see why the model did what it did, including when it was confidently
wrong.

Threading: the loop is synchronous and owns the ViZDoom game, so it runs on a
worker thread and publishes records into a bounded queue. The event loop drains
that queue and fans records out to sockets. The queue drops its oldest entry when
full rather than blocking, because the game clock must never wait on a browser.
"""

from __future__ import annotations

import asyncio
import base64
import io
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .baselines import RandomClient, ScriptedClient
from .client import DecisionClient, DecisionError, LayaMpsClient
from .game import DEFAULT_SCENARIO, make_game
from .loop import DECISION_INTERVAL_MS, DecisionLoop, EpisodeResult, TickRecord
from .questions import BATTERY

STATIC = Path(__file__).parent / "static"
QUEUE_SIZE = 8  # a couple of intervals of slack; beyond that, drop old frames


def encode_frame(buffer: Any) -> str | None:
    """Screen buffer -> base64 JPEG. Handles both of ViZDoom's channel orders."""
    if buffer is None:
        return None
    import numpy as np
    from PIL import Image

    array = np.asarray(buffer)
    if array.ndim == 3 and array.shape[0] == 3:  # (3, h, w) -> (h, w, 3)
        array = np.transpose(array, (1, 2, 0))
    image = Image.fromarray(array.astype("uint8"), mode="RGB")
    sink = io.BytesIO()
    image.save(sink, format="JPEG", quality=70)
    return base64.b64encode(sink.getvalue()).decode("ascii")


def render_record(record: TickRecord, policy: str) -> dict:
    """One websocket message: the frame and the decision that produced it."""
    decision = record.decision
    answers = []
    if decision is not None:
        for name, answer in decision.answers.items():
            answers.append({
                "name": name,
                "type": answer.type,
                "label": answer.label,
                "value": answer.value,
                "confidence": answer.confidence,
                "top_probability": answer.top_probability,
                "distribution": answer.distribution,
            })
    pressed = [name for name, on in zip(record.buttons, record.action) if on]
    return {
        "type": "tick",
        "policy": policy,
        "tick": record.tick,
        "tics_advanced": record.tics_advanced,
        "state": record.state,
        "observation": record.state.get("observation", ""),
        "pressed": pressed,
        "fresh": record.fresh,
        "health": record.health,
        "ammo": record.ammo,
        "kills": record.killcount,
        "latency_ms": None if decision is None else decision.latency_ms,
        "server_ms": None if decision is None else decision.server_ms,
        "answers": answers,
        "frame": encode_frame(record.frame),
    }


@dataclass
class SessionConfig:
    policy: str = "laya"
    scenario: str = DEFAULT_SCENARIO
    interval_ms: float = DECISION_INTERVAL_MS
    fire_threshold: float = 0.5
    url: str = "http://127.0.0.1:8000"


class Session:
    """Owns the worker thread, the game, and the current policy."""

    def __init__(self, config: SessionConfig) -> None:
        self.config = config
        self.records: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self.episodes: list[EpisodeResult] = []
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._running = False

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.error = None
        self._running = True
        self._thread = threading.Thread(target=self._run, name="laya-doom", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None

    def restart_episode(self) -> None:
        """End the current episode; the worker begins a fresh one."""
        self._restart.set()

    def set_policy(self, policy: str) -> None:
        was_running = self.running
        self.stop()
        self.config.policy = policy
        self.episodes = []
        if was_running:
            self.start()

    # -- worker ------------------------------------------------------------

    def _build_client(self) -> DecisionClient:
        if self.config.policy == "scripted":
            return ScriptedClient()
        if self.config.policy == "random":
            return RandomClient()
        return LayaMpsClient(self.config.url)

    def _publish(self, message: dict) -> None:
        try:
            self.records.put_nowait(message)
        except queue.Full:
            # Drop the oldest rather than stall the game clock on a slow browser.
            try:
                self.records.get_nowait()
                self.records.put_nowait(message)
            except (queue.Empty, queue.Full):
                pass

    def _run(self) -> None:
        client = None
        game = None
        try:
            client = self._build_client()
            while not self._stop.is_set():
                self._restart.clear()
                game = make_game(self.config.scenario)
                loop = DecisionLoop(
                    game, client, BATTERY,
                    interval_ms=self.config.interval_ms,
                    fire_threshold=self.config.fire_threshold,
                )
                try:
                    result = loop.run_episode(
                        on_tick=lambda record: self._publish(render_record(record, self.config.policy)),
                        should_stop=lambda: self._stop.is_set() or self._restart.is_set(),
                    )
                finally:
                    loop.close()
                    game.close()
                    game = None
                self.episodes.append(result)
                self._publish({
                    "type": "episode",
                    "policy": self.config.policy,
                    "summary": result.summary(),
                    "score": result.score,
                    "kills": result.killcount,
                    "decisions": result.decisions,
                    "skipped": result.skipped_slots,
                    "stale": result.stale_replies,
                    "errors": result.errors,
                    "latency_p50": result.latency_p50,
                    "latency_p95": result.latency_p95,
                    "decisions_per_second": result.decisions_per_second,
                    "episodes_played": len(self.episodes),
                    "mean_score": sum(e.score for e in self.episodes) / len(self.episodes),
                })
        except DecisionError as exc:
            self.error = str(exc)
            self._publish({"type": "error", "message": str(exc)})
        except Exception as exc:  # keep the server alive and tell the browser why
            self.error = f"{type(exc).__name__}: {exc}"
            self._publish({"type": "error", "message": self.error})
        finally:
            self._running = False
            if game is not None:
                game.close()
            if client is not None:
                client.close()


@dataclass
class Hub:
    """The connected browsers."""

    sockets: set[WebSocket] = field(default_factory=set)

    async def broadcast(self, message: dict) -> None:
        for socket in list(self.sockets):
            try:
                await socket.send_json(message)
            except Exception:
                self.sockets.discard(socket)


def create_app(config: SessionConfig | None = None) -> FastAPI:
    app = FastAPI(title="LAYA plays Doom")
    session = Session(config or SessionConfig())
    hub = Hub()
    app.state.session = session

    @app.on_event("startup")
    async def start_pump() -> None:
        async def pump() -> None:
            while True:
                try:
                    message = session.records.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                await hub.broadcast(message)

        app.state.pump = asyncio.create_task(pump())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        session.stop()
        task = getattr(app.state, "pump", None)
        if task is not None:
            task.cancel()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status() -> dict:
        return {
            "running": session.running,
            "policy": session.config.policy,
            "scenario": session.config.scenario,
            "interval_ms": session.config.interval_ms,
            "fire_threshold": session.config.fire_threshold,
            "episodes": len(session.episodes),
            "error": session.error,
            "questions": {name: question["type"] for name, question in BATTERY.items()},
        }

    @app.post("/api/start")
    def start() -> dict:
        session.start()
        return {"running": session.running}

    @app.post("/api/stop")
    def stop() -> dict:
        session.stop()
        return {"running": session.running}

    @app.post("/api/restart")
    def restart() -> dict:
        session.restart_episode()
        return {"restarted": True}

    @app.post("/api/policy/{policy}")
    def policy(policy: str) -> dict:
        if policy not in {"laya", "scripted", "random"}:
            return {"error": f"unknown policy {policy!r}"}
        session.set_policy(policy)
        return {"policy": session.config.policy, "running": session.running}

    @app.websocket("/ws")
    async def stream(socket: WebSocket) -> None:
        await socket.accept()
        hub.sockets.add(socket)
        try:
            while True:
                await socket.receive_text()  # keepalive; controls go over REST
        except WebSocketDisconnect:
            pass
        finally:
            hub.sockets.discard(socket)

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
