"""Statistiques de diagnostic : elles lisent les octets reçus et ne les modifient jamais."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from audio_capture.protocol import SAMPLE_BYTES, SAMPLE_RATE

FULL_SCALE = 32768.0
GAP_THRESHOLD_S = 0.150  # 3 × la durée nominale d'un paquet (50 ms)


def dbfs(amplitude: float) -> float | None:
    """Niveau en dBFS par rapport à 32768 ; None pour un silence numérique."""
    return 20 * math.log10(amplitude / FULL_SCALE) if amplitude > 0 else None


@dataclass(frozen=True)
class StatsSnapshot:
    window_s: float
    packets: int
    audio_s: float
    rt_ratio: float
    kbps: float
    peak_dbfs: float | None
    rms_dbfs: float | None
    max_gap_ms: float
    gaps: int

    @property
    def packets_per_s(self) -> float:
        return self.packets / self.window_s if self.window_s > 0 else 0.0


class LiveStats:
    """Totaux de session + fenêtre glissante remise à zéro à chaque snapshot."""

    def __init__(self, started_at: float) -> None:
        self._started_at = started_at
        self._last_arrival = started_at
        self._total_frames = 0
        self._reset_window(started_at)

    def _reset_window(self, now: float) -> None:
        self._window_start = now
        self._packets = 0
        self._bytes = 0
        self._peak = 0
        self._sum_sq = 0.0
        self._max_gap = 0.0
        self._gaps = 0

    def add(self, pcm: bytes, now: float) -> None:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.int64)
        interval = now - self._last_arrival
        self._last_arrival = now
        self._max_gap = max(self._max_gap, interval)
        self._gaps += interval > GAP_THRESHOLD_S
        self._packets += 1
        self._bytes += len(pcm)
        self._total_frames += len(pcm) // SAMPLE_BYTES
        if samples.size:
            self._peak = max(self._peak, int(np.abs(samples).max()))
            self._sum_sq += float(np.dot(samples, samples))

    def snapshot(self, now: float) -> StatsSnapshot:
        window = now - self._window_start
        elapsed = now - self._started_at
        frames = self._bytes // SAMPLE_BYTES
        audio_s = self._total_frames / SAMPLE_RATE
        snap = StatsSnapshot(
            window_s=window,
            packets=self._packets,
            audio_s=audio_s,
            rt_ratio=audio_s / elapsed if elapsed > 0 else 0.0,
            kbps=self._bytes * 8 / 1000 / window if window > 0 else 0.0,
            peak_dbfs=dbfs(self._peak),
            rms_dbfs=dbfs(math.sqrt(self._sum_sq / frames)) if frames else None,
            max_gap_ms=self._max_gap * 1000,
            gaps=self._gaps,
        )
        self._reset_window(now)
        return snap
