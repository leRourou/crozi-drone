"""Interface de ② (son → distance au drone), commune à l'estimateur simulé et au futur modèle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioWindow:
    """Fenêtre contiguë du PCM d'une seule session (s16le mono 48 kHz, octets non modifiés).

    t : heure serveur (epoch, s) d'arrivée du paquet qui complète la fenêtre.
    """

    profile: str
    session_id: str
    t: float
    pcm: bytes


@dataclass(frozen=True)
class Range:
    """Distance estimée au drone et incertitude relative (0.10 = ±10 %)."""

    distance_m: float
    uncertainty_rel: float


@dataclass(frozen=True)
class DistanceEstimate:
    """Résultat d'une fenêtre : range vaut None quand aucun drone n'est détecté."""

    profile: str
    t: float
    range: Range | None

    @property
    def drone(self) -> bool:
        return self.range is not None


class DistanceEstimator(Protocol):
    def estimate(self, window: AudioWindow) -> DistanceEstimate: ...
