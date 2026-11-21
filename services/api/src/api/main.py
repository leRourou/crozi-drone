"""Serveur FastAPI : réception temps réel crozidrone.audio-stream.v1 sur /ws/audio,
état général des téléphones sur /ws/state."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.logfmt import kv, short_browser
from api.profiles import Profile, load_profiles
from api.settings import Settings, load_settings
from api.state import PhoneRegistry, PhoneSession
from audio_capture.protocol import (
    End,
    Hello,
    Ping,
    ProtocolError,
    parse_control,
    parse_hello,
    parse_packet,
)
from audio_capture.recording import WavRecorder
from audio_capture.session import EndAck, StreamSession
from audio_capture.stats import StatsSnapshot
from distance_estimation.estimator import DistanceEstimator
from distance_estimation.scripted import ScriptedEstimator
from distance_estimation.windows import WindowAccumulator

STATS_PERIOD_S = 1.0
POLICY_VIOLATION = 1008
DEFAULT_RECORDINGS = Path(
    "recordings"
)  # relatif au dossier de lancement ; RECORDINGS_DIR prioritaire

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("crozidrone.audio")


# Déposé dans l'inbox d'une connexion par le registre quand une session plus récente du même
# téléphone démarre. Comparé par identité : un message client ne peut pas l'imiter.
_REPLACED: dict[str, Any] = {"type": "crozidrone.replaced"}


@dataclass(frozen=True)
class Estimation:
    """② actif : l'estimateur et la taille des fenêtres qu'il reçoit (pas l'un sans l'autre)."""

    estimator: DistanceEstimator
    window_frames: int


def make_estimation(settings: Settings, profiles: tuple[Profile, ...]) -> Estimation | None:
    """None quand DISTANCE_ESTIMATOR=none : aucune détection, donc aucun faux drone affiché."""
    if settings.estimator == "none":
        return None
    positions = {p.id: (p.x_m, p.y_m, p.z_m) for p in profiles}
    return Estimation(ScriptedEstimator(positions), settings.window_frames)


def _recorder_for(hello: Hello) -> WavRecorder | None:
    if os.environ.get("SAVE_SESSIONS") != "1":
        return None
    folder = Path(os.environ.get("RECORDINGS_DIR", DEFAULT_RECORDINGS))
    return WavRecorder(folder / f"{hello.profile}_{hello.session_id}.wav")


def _log_start(sid: str, hello: Hello) -> None:
    s = hello.capture_settings
    log.info(
        kv(
            "session_start",
            sid=sid,
            profile=hello.profile,
            contract=hello.contract,
            browser=short_browser(hello.user_agent),
            mic=s.get("microphone_label"),
            input_channels=s.get("input_channels"),
            ec=s.get("echoCancellation"),
            ns=s.get("noiseSuppression"),
            agc=s.get("autoGainControl"),
        )
    )
    if hello.contract == "edth.web-pcm.webkit.v1":
        log.warning(kv("webkit_profile", sid=sid, note="NS/AGC non vérifiables"))


def _stats_message(snap: StatsSnapshot) -> dict[str, Any]:
    return {
        "type": "stats",
        "packets_per_s": snap.packets_per_s,
        "audio_s": snap.audio_s,
        "rt_ratio": snap.rt_ratio,
        "kbps": snap.kbps,
        "peak_dbfs": snap.peak_dbfs,
        "rms_dbfs": snap.rms_dbfs,
        "max_gap_ms": snap.max_gap_ms,
        "gaps": snap.gaps,
    }


def _log_stats(sid: str, snap: StatsSnapshot) -> None:
    level = logging.WARNING if snap.gaps else logging.INFO
    log.log(
        level,
        kv(
            "stats",
            sid=sid,
            pps=snap.packets_per_s,
            audio_s=snap.audio_s,
            rt=snap.rt_ratio,
            kbps=snap.kbps,
            peak_dbfs=snap.peak_dbfs,
            rms_dbfs=snap.rms_dbfs,
            max_gap_ms=snap.max_gap_ms,
            gaps=snap.gaps,
        ),
    )


def _match_label(client_sha: str | None, ack: EndAck | None) -> str:
    if ack is None or client_sha is None:
        return "n/a"
    return "✅" if ack.match else "❌"


class Connection:
    """Une connexion WebSocket = une session. Un seul écrivain : la boucle run()."""

    def __init__(
        self,
        ws: WebSocket,
        registry: PhoneRegistry,
        estimation: Estimation | None = None,
    ) -> None:
        self.ws = ws
        self.registry = registry
        self.estimation = estimation
        self.phone: PhoneSession | None = None
        self.windows: WindowAccumulator | None = None
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.session: StreamSession | None = None
        self.recorder: WavRecorder | None = None
        self.sid = "-"

    async def _read(self) -> None:
        while True:
            message = await self.ws.receive()
            await self.inbox.put(message)
            if message["type"] == "websocket.disconnect":
                return

    async def run(self) -> None:
        await self.ws.accept()
        reader = asyncio.create_task(self._read())
        try:
            await self._serve()
        except ProtocolError as err:
            await self._refuse(err)
        finally:
            reader.cancel()
            if self.phone is not None:
                self.phone.end(time.monotonic())
            if self.recorder is not None:
                self.recorder.close()

    async def _refuse(self, err: ProtocolError) -> None:
        log.error(kv(err.code, sid=self.sid, detail=err.message))
        if self.session is not None:
            self._log_end("error")
        with contextlib.suppress(Exception):
            await self.ws.send_json({"type": "error", "code": err.code, "message": err.message})
            await self.ws.close(POLICY_VIOLATION)

    async def _serve(self) -> None:
        first = await self.inbox.get()
        if first["type"] == "websocket.disconnect":
            return
        if first.get("text") is None:
            raise ProtocolError("invalid_hello", "first message must be a text hello")
        self._open(parse_hello(first["text"], self.registry.ids))
        await self.ws.send_json(
            {
                "type": "ready",
                "session_id": str(self.session.hello.session_id),
                "profile": self.session.hello.profile,
                "server_time": time.time(),
            }
        )
        await self._stream()

    def _open(self, hello: Hello) -> None:
        self.sid = str(hello.session_id)[:8]
        self.recorder = _recorder_for(hello)
        sink = self.recorder.write if self.recorder else None
        now = time.monotonic()
        self.session = StreamSession(hello, started_at=now, sink=sink)
        session_id = str(hello.session_id)
        self.phone = self.registry.start(
            hello.profile, session_id, hello.contract, self._replaced, now
        )
        if self.estimation is not None:
            frames = self.estimation.window_frames
            self.windows = WindowAccumulator(hello.profile, session_id, frames)
        _log_start(self.sid, hello)

    def _replaced(self) -> None:
        self.inbox.put_nowait(_REPLACED)

    def _estimate(self, pcm: bytes, now: float) -> None:
        if self.windows is None:
            return
        for window in self.windows.add(pcm, time.time()):
            self.phone.estimate(self.estimation.estimator.estimate(window), now)

    async def _stream(self) -> None:
        next_tick = time.monotonic() + STATS_PERIOD_S
        while True:
            try:
                timeout = max(0.0, next_tick - time.monotonic())
                message = await asyncio.wait_for(self.inbox.get(), timeout)
            except TimeoutError:
                next_tick += STATS_PERIOD_S
                await self._push_stats()
                continue
            if await self._handle(message):
                return

    async def _push_stats(self) -> None:
        snap = self.session.snapshot(time.monotonic())
        self.phone.stats(snap.rt_ratio, snap.rms_dbfs)
        _log_stats(self.sid, snap)
        await self.ws.send_json(_stats_message(snap))

    async def _handle(self, message: dict[str, Any]) -> bool:
        """Traite un message ; renvoie True quand la session est terminée."""
        if message["type"] == "websocket.disconnect":
            log.warning(kv("disconnect", sid=self.sid, code=message.get("code")))
            self._log_end("disconnect")
            return True
        if message is _REPLACED:
            raise ProtocolError("session_replaced", "a newer session took over this phone")
        if message.get("bytes") is not None:
            now = time.monotonic()
            pkt = parse_packet(message["bytes"])
            self.session.accept(pkt, now)
            self.phone.packet(now)
            self._estimate(pkt.pcm, now)
            return False
        control = parse_control(message.get("text") or "")
        if isinstance(control, Ping):
            await self.ws.send_json({"type": "pong", "t": control.t})
            return False
        await self._end(control)
        return True

    async def _end(self, end: End) -> None:
        ack = self.session.finish(end)
        self._log_end(end.reason, end, ack)
        await self.ws.send_json(
            {"type": "end_ack", **asdict(ack), "profile": self.session.hello.profile}
        )
        await self.ws.close()

    def _log_end(self, reason: str, end: End | None = None, ack: EndAck | None = None) -> None:
        session = self.session
        client_sha = end.pcm_sha256 if end else None
        label = _match_label(client_sha, ack)
        level = logging.INFO if label == "✅" else logging.WARNING
        log.log(
            level,
            kv(
                "session_end",
                sid=self.sid,
                profile=session.hello.profile,
                duration_s=time.monotonic() - session.started_at,
                frames=session.frames_received,
                client_frames=end.frames if end else None,
                server_sha=session.pcm_sha256[:16],
                client_sha=client_sha[:16] if client_sha else None,
                match=label,
                reason=reason,
            ),
        )


async def _push_state(ws: WebSocket, registry: PhoneRegistry, period_s: float) -> None:
    while True:
        await ws.send_json(registry.snapshot(time.monotonic(), time.time()))
        await asyncio.sleep(period_s)


async def _serve_state(ws: WebSocket, registry: PhoneRegistry, period_s: float) -> None:
    """Envoie l'état tout de suite puis toutes les STATE_PERIOD_MS, jusqu'à la déconnexion."""
    await ws.accept()
    pusher = asyncio.create_task(_push_state(ws, registry, period_s))
    try:
        while (await ws.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        pusher.cancel()


def create_app(
    front_dir: Path | None, profiles: tuple[Profile, ...], settings: Settings | None = None
) -> FastAPI:
    """front_dir : build Vite servi à la racine (même origine que /ws/audio), ou None (dev).
    profiles : contrat contracts/profiles.json, chargé une fois au démarrage.
    settings : réglages du temps réel (load_settings lit l'environnement)."""
    settings = settings or Settings()
    estimation = make_estimation(settings, profiles)
    registry = PhoneRegistry(profiles, settings)

    async def audio_stream(ws: WebSocket) -> None:
        await Connection(ws, registry, estimation).run()

    async def state_stream(ws: WebSocket) -> None:
        await _serve_state(ws, registry, settings.state_period_s)

    application = FastAPI(title="Crozidrone audio stream")
    application.add_api_websocket_route("/ws/audio", audio_stream)
    application.add_api_websocket_route("/ws/state", state_stream)
    if front_dir is not None:
        # Adresse courte de la page d'état ; à déclarer avant le montage statique sur "/".
        application.add_api_route("/display", lambda: RedirectResponse("/display.html"))
        application.mount("/", StaticFiles(directory=front_dir, html=True), name="front")
    return application


_front_dir = os.environ.get("FRONT_DIR")
app = create_app(
    Path(_front_dir) if _front_dir else None,
    load_profiles(),
    load_settings(),
)
