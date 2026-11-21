"""Découpe le PCM d'une session en fenêtres contiguës, sans recouvrement ni recollage."""

from __future__ import annotations

from distance_estimation.estimator import AudioWindow

SAMPLE_BYTES = 2
WINDOW_FRAMES = 24_000  # 500 ms à 48 kHz ; à aligner sur l'entrée du futur modèle


class WindowAccumulator:
    """Un accumulateur par session : une nouvelle session repart d'un tampon vide."""

    def __init__(self, profile: str, session_id: str, frames: int = WINDOW_FRAMES) -> None:
        self._profile = profile
        self._session_id = session_id
        self._size = frames * SAMPLE_BYTES
        self._buffer = bytearray()

    def add(self, pcm: bytes, t: float) -> list[AudioWindow]:
        self._buffer += pcm
        windows = []
        while len(self._buffer) >= self._size:
            chunk = bytes(self._buffer[: self._size])
            del self._buffer[: self._size]
            windows.append(AudioWindow(self._profile, self._session_id, t, chunk))
        return windows
