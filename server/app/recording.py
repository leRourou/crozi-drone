"""Option SAVE_SESSIONS : octets reçus écrits tels quels sous un en-tête WAV 48 kHz mono 16 bits."""

from __future__ import annotations

import wave
from pathlib import Path
from types import TracebackType

from app.protocol import SAMPLE_BYTES, SAMPLE_RATE


class WavRecorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(path), "wb")  # noqa: SIM115 - fermé par close()
        self._wav.setnchannels(1)
        self._wav.setsampwidth(SAMPLE_BYTES)
        self._wav.setframerate(SAMPLE_RATE)

    def write(self, pcm: bytes) -> None:
        self._wav.writeframesraw(pcm)

    def close(self) -> None:
        self._wav.close()  # réécrit les tailles de l'en-tête

    def __enter__(self) -> WavRecorder:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
