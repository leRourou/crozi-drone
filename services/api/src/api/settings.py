"""Réglages du temps réel, lus dans l'environnement au démarrage.

Seul services/api lit l'environnement ; les modules reçoivent des valeurs. Une valeur invalide lève
ValueError à la construction : le serveur ne démarre pas avec un réglage absurde.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields

from audio_capture.protocol import SAMPLE_RATE

ESTIMATORS = ("none", "scripted")

# Champ → variable d'environnement (aussi utilisée dans les messages d'erreur).
_VARIABLES = {
    "estimator": "DISTANCE_ESTIMATOR",
    "window_ms": "DISTANCE_WINDOW_MS",
    "state_period_ms": "STATE_PERIOD_MS",
    "stale_after_ms": "STALE_AFTER_MS",
    "detection_fresh_ms": "DETECTION_FRESH_MS",
}


@dataclass(frozen=True)
class Settings:
    estimator: str = "none"  # none : aucun faux drone affiché ; scripted : mock de ②
    window_ms: int = 250  # taille d'une fenêtre analysée par ② (= une estimation par fenêtre)
    state_period_ms: int = 250  # envoi de l'état sur /ws/state
    stale_after_ms: int = 1000  # session sans paquet depuis plus longtemps : « stale »
    detection_fresh_ms: int = 2000  # au-delà, une détection n'est plus « fresh »

    def __post_init__(self) -> None:
        if self.estimator not in ESTIMATORS:
            raise ValueError(
                f"DISTANCE_ESTIMATOR must be one of {ESTIMATORS}, got {self.estimator!r}"
            )
        for field in fields(self)[1:]:
            value = getattr(self, field.name)
            if type(value) is not int or value <= 0:
                variable = _VARIABLES[field.name]
                raise ValueError(f"{variable} must be a positive integer, got {value!r}")

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


def _milliseconds(variable: str, raw: str) -> int:
    if not raw.isdigit():
        raise ValueError(f"{variable} must be a positive integer, got {raw!r}")
    return int(raw)


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    values: dict[str, str | int] = {}
    for name, variable in _VARIABLES.items():
        if variable not in env:
            continue
        raw = env[variable]
        values[name] = raw if name == "estimator" else _milliseconds(variable, raw)
    return Settings(**values)
