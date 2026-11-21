"""Réglages du temps réel et du drone simulé, lus dans l'environnement au démarrage.

Seul services/api lit l'environnement ; les modules reçoivent des valeurs. Une valeur invalide lève
ValueError à la construction : le serveur ne démarre pas avec un réglage absurde.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from audio_capture.protocol import SAMPLE_RATE

ESTIMATORS = ("none", "scripted", "model")
_SHA = re.compile(r"[0-9a-f]{40}")
_FOLDER = re.compile(r"[\w.-]*[\w-][\w.-]*")  # un nom de dossier simple : ni "/", ni "." ou ".."

# Nature d'une valeur : durée en ms (entier > 0), réel > 0, réel ≥ 0, réel quelconque (fini),
# texte facultatif (une variable vide compte comme absente).
_MS, _POSITIVE, _NON_NEGATIVE, _REAL, _TEXT = "ms", "positive", "non-negative", "real", "text"


def _setting(variable: str, kind: str, default: Any) -> Any:
    return field(default=default, metadata={"env": variable, "kind": kind})


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


_VALID: dict[str, Callable[[Any], bool]] = {
    _MS: lambda v: type(v) is int and v > 0,
    _POSITIVE: lambda v: _finite(v) and v > 0,
    _NON_NEGATIVE: lambda v: _finite(v) and v >= 0,
    _REAL: _finite,
    _TEXT: lambda v: v is None or (type(v) is str and v != ""),
}


def _valid(kind: str, value: Any) -> bool:
    return _VALID[kind](value)


@dataclass(frozen=True)
class Settings:
    estimator: str = field(default="none", metadata={"env": "DISTANCE_ESTIMATOR"})
    # Temps réel
    window_ms: int = _setting("DISTANCE_WINDOW_MS", _MS, 250)  # fenêtre analysée par ②
    state_period_ms: int = _setting("STATE_PERIOD_MS", _MS, 250)  # envoi de l'état
    stale_after_ms: int = _setting("STALE_AFTER_MS", _MS, 1000)  # streaming → stale
    detection_fresh_ms: int = _setting("DETECTION_FRESH_MS", _MS, 2000)  # détection périmée
    fusion_spread_ms: int = _setting("FUSION_SPREAD_MS", _MS, 500)  # écart max entre détections
    # Piste du drone (③, filtre de Kalman étendu)
    track_accel_std: float = _setting("TRACK_ACCEL_STD", _POSITIVE, 1.0)  # m/s², grand = réactif
    track_timeout_ms: int = _setting("TRACK_TIMEOUT_MS", _MS, 1000)  # piste perdue sans distance
    track_altitude_m: float = _setting("TRACK_ALTITUDE_M", _NON_NEGATIVE, 1.5)  # altitude attendue
    track_altitude_std_m: float = _setting("TRACK_ALTITUDE_STD_M", _POSITIVE, 0.5)  # sa souplesse
    # Drone simulé (DISTANCE_ESTIMATOR=scripted) : cercle près des téléphones, repère de la salle
    scripted_offset_east_m: float = _setting("SCRIPTED_OFFSET_EAST_M", _REAL, 0.5)
    scripted_offset_north_m: float = _setting("SCRIPTED_OFFSET_NORTH_M", _REAL, 3.0)
    scripted_radius_m: float = _setting("SCRIPTED_RADIUS_M", _POSITIVE, 3.0)
    scripted_altitude_m: float = _setting("SCRIPTED_ALTITUDE_M", _NON_NEGATIVE, 1.5)
    scripted_period_s: float = _setting("SCRIPTED_PERIOD_S", _POSITIVE, 20.0)
    scripted_range_m: float = _setting("SCRIPTED_RANGE_M", _POSITIVE, 5.0)
    scripted_uncertainty: float = _setting("SCRIPTED_UNCERTAINTY", _POSITIVE, 0.10)
    scripted_noise: float = _setting("SCRIPTED_NOISE", _NON_NEGATIVE, 0.0)  # écart-type relatif
    # Vrai modèle (DISTANCE_ESTIMATOR=model) : bundle local, sinon repo HF à révision épinglée
    model_dir: str | None = _setting("DISTANCE_MODEL_DIR", _TEXT, None)
    model_repo: str | None = _setting("DISTANCE_MODEL_REPO", _TEXT, None)
    model_revision: str | None = _setting("DISTANCE_MODEL_REVISION", _TEXT, None)
    model_release: str | None = _setting("DISTANCE_MODEL_RELEASE", _TEXT, None)  # dossier du repo
    model_uncertainty: float = _setting("MODEL_UNCERTAINTY", _POSITIVE, 0.10)  # ± relatif annoncé
    hf_token: str | None = field(  # secret : absent du repr (logs, traces)
        default=None, repr=False, metadata={"env": "HF_TOKEN", "kind": _TEXT}
    )

    def __post_init__(self) -> None:
        if self.estimator not in ESTIMATORS:
            raise ValueError(
                f"DISTANCE_ESTIMATOR must be one of {ESTIMATORS}, got {self.estimator!r}"
            )
        for f in fields(self)[1:]:
            value = getattr(self, f.name)
            if not _valid(f.metadata["kind"], value):
                raise ValueError(f"{f.metadata['env']} must be {f.metadata['kind']}, got {value!r}")
        if self.estimator == "model" and self.model_dir is None:
            self._check_model_source()

    def _check_model_source(self) -> None:
        """Sans bundle local : un repo et une révision épinglée (sha de commit, pas une branche)."""
        if self.model_repo is None:
            raise ValueError("DISTANCE_MODEL_REPO is required (or DISTANCE_MODEL_DIR)")
        if self.model_revision is None or not _SHA.fullmatch(self.model_revision):
            raise ValueError(
                f"DISTANCE_MODEL_REVISION must be a 40-hex commit sha, got {self.model_revision!r}"
            )
        if self.model_release is None or not _FOLDER.fullmatch(self.model_release):
            raise ValueError(
                f"DISTANCE_MODEL_RELEASE must name the release folder, got {self.model_release!r}"
            )

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

    @property
    def track_timeout_s(self) -> float:
        return self.track_timeout_ms / 1000


def _parse(variable: str, kind: str | None, raw: str) -> str | int | float | None:
    if kind is None:
        return raw
    if kind == _TEXT:
        return raw or None
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
