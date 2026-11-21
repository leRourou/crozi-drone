"""Protocole crozidrone.audio-stream.v1 : parsing et validation des messages à la frontière.

Les données venant du client sont vérifiées ici, une seule fois ; le reste du serveur
manipule des objets déjà valides (Hello, Packet, Ping, End).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, get_args

PROTOCOL = "crozidrone.audio-stream.v1"
KNOWN_CONTRACTS = frozenset({"edth.web-pcm.v1", "edth.web-pcm.webkit.v1"})
# Téléphones de l'équipe ; même liste dans web/src/capture/profiles.ts (réf. docs/protocol.md).
KNOWN_PROFILES = frozenset({"axel", "maxence", "tristan", "noe", "charlene"})
SAMPLE_RATE = 48_000
SEQ_BYTES = 4
SAMPLE_BYTES = 2

# Format PCM imposé par les deux contrats EDTH (champs de captureSettings).
# TODO: importer les validateurs complets depuis collector/contract.py quand Noé l'aura extrait
# d'app.py (app.py importe Streamlit : ne pas l'importer ici).
REQUIRED_FORMAT: dict[str, Any] = {
    "sample_rate": SAMPLE_RATE,
    "channels": 1,
    "sample_format": "pcm_s16le",
    "channel_selection": "first",
    "recorder": "audio_worklet_pcm",
}

EndReason = Literal["manual", "limit", "network_too_slow", "error"]
END_REASONS: frozenset[str] = frozenset(get_args(EndReason))


class ProtocolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Hello:
    session_id: uuid.UUID
    profile: str
    contract: str
    capture_settings: dict[str, Any]
    captured_at: str
    user_agent: str


@dataclass(frozen=True)
class Packet:
    seq: int
    pcm: bytes

    @property
    def frames(self) -> int:
        return len(self.pcm) // SAMPLE_BYTES


@dataclass(frozen=True)
class Ping:
    t: float


@dataclass(frozen=True)
class End:
    reason: EndReason
    frames: int
    pcm_sha256: str | None


def _same(value: Any, expected: Any) -> bool:
    """Égalité stricte : True ne vaut pas 1, 48000.0 ne vaut pas 48000."""
    return type(value) is type(expected) and value == expected


def _load_object(text: str, code: str) -> dict[str, Any]:
    try:
        obj = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(code, "message is not valid JSON") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(code, "message must be a JSON object")
    return obj


def _parse_uuid(value: Any) -> uuid.UUID:
    if not isinstance(value, str):
        raise ProtocolError("invalid_hello", "session_id must be a UUID string")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ProtocolError("invalid_hello", f"session_id is not a UUID: {value!r}") from exc


def _check_profile(value: Any) -> str:
    if not isinstance(value, str) or value not in KNOWN_PROFILES:
        raise ProtocolError("unknown_profile", f"profile={value!r}")
    return value


def _check_settings(settings: Any) -> str:
    if not isinstance(settings, dict):
        raise ProtocolError("invalid_hello", "capture_settings must be an object")
    contract = settings.get("capture_contract")
    if contract not in KNOWN_CONTRACTS:
        raise ProtocolError("unknown_contract", f"capture_contract={contract!r}")
    for key, expected in REQUIRED_FORMAT.items():
        if not _same(settings.get(key), expected):
            detail = f"{key}={settings.get(key)!r} expected={expected!r}"
            raise ProtocolError("invalid_format", detail)
    return contract


def parse_hello(text: str) -> Hello:
    obj = _load_object(text, "invalid_hello")
    if obj.get("type") != "hello":
        raise ProtocolError("invalid_hello", "first message must be hello")
    if obj.get("protocol") != PROTOCOL:
        raise ProtocolError("unknown_protocol", f"protocol={obj.get('protocol')!r}")
    session_id = _parse_uuid(obj.get("session_id"))
    profile = _check_profile(obj.get("profile"))
    settings = obj.get("capture_settings")
    contract = _check_settings(settings)
    return Hello(
        session_id=session_id,
        profile=profile,
        contract=contract,
        capture_settings=settings,
        captured_at=str(obj.get("captured_at", "")),
        user_agent=str(obj.get("user_agent", "")),
    )


def parse_packet(data: bytes) -> Packet:
    if len(data) < SEQ_BYTES + SAMPLE_BYTES:
        raise ProtocolError("invalid_packet", f"packet too short: {len(data)} bytes")
    pcm = data[SEQ_BYTES:]
    if len(pcm) % SAMPLE_BYTES:
        raise ProtocolError("invalid_packet", f"odd PCM length: {len(pcm)} bytes")
    return Packet(seq=int.from_bytes(data[:SEQ_BYTES], "little"), pcm=pcm)


def _parse_end(obj: dict[str, Any]) -> End:
    reason, frames, digest = obj.get("reason"), obj.get("frames"), obj.get("pcm_sha256")
    if reason not in END_REASONS:
        raise ProtocolError("unexpected_message", f"end.reason={reason!r}")
    if type(frames) is not int or frames < 0:
        raise ProtocolError("unexpected_message", f"end.frames={frames!r}")
    if digest is not None and not isinstance(digest, str):
        raise ProtocolError("unexpected_message", "end.pcm_sha256 must be a string")
    return End(reason=reason, frames=frames, pcm_sha256=digest)


def parse_control(text: str) -> Ping | End:
    obj = _load_object(text, "unexpected_message")
    kind = obj.get("type")
    if kind == "ping" and isinstance(obj.get("t"), int | float):
        return Ping(t=float(obj["t"]))
    if kind == "end":
        return _parse_end(obj)
    raise ProtocolError("unexpected_message", f"unexpected text message type={kind!r}")
