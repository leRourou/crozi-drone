"""Réglages du temps réel et du drone simulé, lus dans l'environnement au démarrage.

Seul services/api lit l'environnement ; les modules reçoivent des valeurs. Une valeur invalide lève
ValueError à la construction : le serveur ne démarre pas avec un réglage absurde.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from audio_capture.protocol import SAMPLE_RATE

ESTIMATORS = ("none", "scripted")

# Nature d'une valeur : durée en ms (entier > 0), réel > 0, réel ≥ 0, réel quelconque (fini).
_MS, _POSITIVE, _NON_NEGATIVE, _REAL = "ms", "positive", "non-negative", "real"


def _setting(variable: str, kind: str, default: Any) -> Any:
    return field(default=default, metadata={"env": variable, "kind": kind})


def _valid(kind: str, value: Any) -> bool:
    if kind == _MS:
        return type(value) is int and value > 0
    if type(value) not in (int, float) or not math.isfinite(value):
        return False
    return kind == _REAL or value > 0 or (kind == _NON_NEGATIVE and value == 0)


@dataclass(frozen=True)
class Settings:
    estimator: str = field(default="none", metadata={"env": "DISTANCE_ESTIMATOR"})
    # Temps réel
    window_ms: int = _setting("DISTANCE_WINDOW_MS", _MS, 250)  # fenêtre analysée par ②
    state_period_ms: int = _setting("STATE_PERIOD_MS", _MS, 250)  # envoi de l'état
    stale_after_ms: int = _setting("STALE_AFTER_MS", _MS, 1000)  # streaming → stale
    detection_fresh_ms: int = _setting("DETECTION_FRESH_MS", _MS, 2000)  # détection périmée
    fusion_spread_ms: int = _setting("FUSION_SPREAD_MS", _MS, 500)  # écart max entre détections
    # Drone simulé (DISTANCE_ESTIMATOR=scripted) : cercle près des téléphones, repère de la salle
    scripted_offset_east_m: float = _setting("SCRIPTED_OFFSET_EAST_M", _REAL, 0.5)
    scripted_offset_north_m: float = _setting("SCRIPTED_OFFSET_NORTH_M", _REAL, 3.0)
    scripted_radius_m: float = _setting("SCRIPTED_RADIUS_M", _POSITIVE, 3.0)
    scripted_altitude_m: float = _setting("SCRIPTED_ALTITUDE_M", _NON_NEGATIVE, 1.5)
    scripted_period_s: float = _setting("SCRIPTED_PERIOD_S", _POSITIVE, 20.0)
    scripted_range_m: float = _setting("SCRIPTED_RANGE_M", _POSITIVE, 5.0)
    scripted_uncertainty: float = _setting("SCRIPTED_UNCERTAINTY", _POSITIVE, 0.10)

    def __post_init__(self) -> None:
        if self.estimator not in ESTIMATORS:
            raise ValueError(
                f"DISTANCE_ESTIMATOR must be one of {ESTIMATORS}, got {self.estimator!r}"
            )
        for f in fields(self)[1:]:
            value = getattr(self, f.name)
            if not _valid(f.metadata["kind"], value):
                raise ValueError(f"{f.metadata['env']} must be {f.metadata['kind']}, got {value!r}")

    @property
    def window_frames(self) -> int:
        return self.window_ms * SAMPLE_RATE // 1000

    @property
    def state_period_s(self) -> float:
        return self.state_period_ms / 1000

    @property
    def stale_after_s(self) -> float:
        return self.stale_after_ms / 1000

    @property
    def detection_fresh_s(self) -> float:
        return self.detection_fresh_ms / 1000

    @property
    def fusion_spread_s(self) -> float:
        return self.fusion_spread_ms / 1000


def _parse(variable: str, kind: str | None, raw: str) -> str | int | float:
    if kind is None:
        return raw
    if kind == _MS:
        if not raw.isdigit():
            raise ValueError(f"{variable} must be a positive integer (ms), got {raw!r}")
        return int(raw)
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{variable} must be a number, got {raw!r}") from None


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    values: dict[str, Any] = {}
    for f in fields(Settings):
        variable = f.metadata["env"]
        if variable in env:
            values[f.name] = _parse(variable, f.metadata.get("kind"), env[variable])
    return Settings(**values)
