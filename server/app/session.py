"""Une session = une capture = un flux continu d'échantillons, jamais recollé à un autre."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from app.protocol import End, Hello, Packet, ProtocolError
from app.stats import LiveStats, StatsSnapshot


@dataclass(frozen=True)
class EndAck:
    frames_received: int
    pcm_sha256: str
    match: bool


class StreamSession:
    def __init__(
        self,
        hello: Hello,
        started_at: float,
        sink: Callable[[bytes], None] | None = None,
    ) -> None:
        self.hello = hello
        self.started_at = started_at
        self.frames_received = 0
        self._expected_seq = 0
        self._sha = hashlib.sha256()
        self._stats = LiveStats(started_at)
        self._sink = sink

    @property
    def pcm_sha256(self) -> str:
        return self._sha.hexdigest()

    def accept(self, packet: Packet, now: float) -> None:
        if packet.seq != self._expected_seq:
            raise ProtocolError("discontinuity", f"expected={self._expected_seq} got={packet.seq}")
        self._expected_seq += 1
        self._sha.update(packet.pcm)
        self.frames_received += packet.frames
        self._stats.add(packet.pcm, now)
        if self._sink is not None:
            self._sink(packet.pcm)

    def snapshot(self, now: float) -> StatsSnapshot:
        return self._stats.snapshot(now)

    def finish(self, end: End) -> EndAck:
        digest = self.pcm_sha256
        match = end.pcm_sha256 == digest and end.frames == self.frames_received
        return EndAck(frames_received=self.frames_received, pcm_sha256=digest, match=match)
