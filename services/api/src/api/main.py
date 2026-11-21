"""Serveur FastAPI : réception temps réel crozidrone.audio-stream.v1 sur /ws/audio."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from api.logfmt import kv, short_browser
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

STATS_PERIOD_S = 1.0
POLICY_VIOLATION = 1008
DEFAULT_RECORDINGS = Path(
    "recordings"
)  # relatif au dossier de lancement ; RECORDINGS_DIR prioritaire

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("crozidrone.audio")


def _recorder_for(hello: Hello) -> WavRecorder | None:
    if os.environ.get("SAVE_SESSIONS") != "1":
        return None
    folder = Path(os.environ.get("RECORDINGS_DIR", DEFAULT_RECORDINGS))
    return WavRecorder(folder / f"{hello.session_id}.wav")


def _log_start(sid: str, hello: Hello) -> None:
    s = hello.capture_settings
    log.info(
        kv(
            "session_start",
            sid=sid,
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

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
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
        self._open(parse_hello(first["text"]))
        await self.ws.send_json(
            {
                "type": "ready",
                "session_id": str(self.session.hello.session_id),
                "server_time": time.time(),
            }
        )
        await self._stream()

    def _open(self, hello: Hello) -> None:
        self.sid = str(hello.session_id)[:8]
        self.recorder = _recorder_for(hello)
        sink = self.recorder.write if self.recorder else None
        self.session = StreamSession(hello, started_at=time.monotonic(), sink=sink)
        _log_start(self.sid, hello)

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
        _log_stats(self.sid, snap)
        await self.ws.send_json(_stats_message(snap))

    async def _handle(self, message: dict[str, Any]) -> bool:
        """Traite un message ; renvoie True quand la session est terminée."""
        if message["type"] == "websocket.disconnect":
            log.warning(kv("disconnect", sid=self.sid, code=message.get("code")))
            self._log_end("disconnect")
            return True
        if message.get("bytes") is not None:
            self.session.accept(parse_packet(message["bytes"]), time.monotonic())
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
        await self.ws.send_json({"type": "end_ack", **asdict(ack)})
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
                duration_s=time.monotonic() - session.started_at,
                frames=session.frames_received,
                client_frames=end.frames if end else None,
                server_sha=session.pcm_sha256[:16],
                client_sha=client_sha[:16] if client_sha else None,
                match=label,
                reason=reason,
            ),
        )


async def audio_stream(ws: WebSocket) -> None:
    await Connection(ws).run()


def create_app(front_dir: Path | None) -> FastAPI:
    """front_dir : build Vite servi à la racine (même origine que /ws/audio), ou None (dev)."""
    application = FastAPI(title="Crozidrone audio stream")
    application.add_api_websocket_route("/ws/audio", audio_stream)
    if front_dir is not None:
        application.mount("/", StaticFiles(directory=front_dir, html=True), name="front")
    return application


_front_dir = os.environ.get("FRONT_DIR")
app = create_app(Path(_front_dir) if _front_dir else None)
