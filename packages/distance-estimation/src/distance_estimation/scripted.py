"""Estimateur simulé (en attendant le modèle) : un drone virtuel suit un cercle connu.

La distance renvoyée est la vraie distance drone ↔ téléphone à l'instant de la fenêtre : la vérité
terrain est connue, ce qui permet de tester la suite (③, ④). Le contenu audio est ignoré, mais une
estimation n'est produite que pour une fenêtre réellement reçue.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from distance_estimation.estimator import AudioWindow, DistanceEstimate, Range

Point = tuple[float, float, float]

DEFAULT_RANGE_M = 30.0
DEFAULT_UNCERTAINTY = 0.10  # = tol par défaut de localiser_drone


@dataclass(frozen=True)
class CircleTrajectory:
    """Cercle horizontal à l'altitude center[2], parcouru dans le sens trigonométrique."""

    center: Point
    radius_m: float
    period_s: float

    def position(self, t: float) -> Point:
        angle = 2 * math.pi * t / self.period_s
        cx, cy, cz = self.center
        return (cx + self.radius_m * math.cos(angle), cy + self.radius_m * math.sin(angle), cz)


def circle_around(phones: Mapping[str, Point]) -> CircleTrajectory:
    """Cercle de 20 m centré 20 m à l'est du barycentre, à 10 m de haut : il passe au-dessus des
    téléphones puis s'en éloigne au-delà de la portée de détection."""
    n = len(phones)
    bx = sum(p[0] for p in phones.values()) / n
    by = sum(p[1] for p in phones.values()) / n
    return CircleTrajectory(center=(bx + 20.0, by, 10.0), radius_m=20.0, period_s=60.0)


class ScriptedEstimator:
    def __init__(
        self,
        phones: Mapping[str, Point],
        trajectory: CircleTrajectory | None = None,
        detection_range_m: float = DEFAULT_RANGE_M,
        uncertainty_rel: float = DEFAULT_UNCERTAINTY,
    ) -> None:
        self._phones = dict(phones)
        self._trajectory = trajectory or circle_around(phones)
        self._detection_range_m = detection_range_m
        self._uncertainty_rel = uncertainty_rel

    def estimate(self, window: AudioWindow) -> DistanceEstimate:
        drone = self._trajectory.position(window.t)
        distance = math.dist(drone, self._phones[window.profile])
        if distance > self._detection_range_m:
            return DistanceEstimate(window.profile, window.t, None)
        return DistanceEstimate(window.profile, window.t, Range(distance, self._uncertainty_rel))
