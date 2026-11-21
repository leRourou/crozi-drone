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


def circle_near(
    phones: Mapping[str, Point],
    east_m: float,
    north_m: float,
    radius_m: float,
    altitude_m: float,
    period_s: float,
) -> CircleTrajectory:
    """Cercle centré sur le barycentre des téléphones décalé de east_m vers l'est (+x) et north_m
    vers le nord (−y : dans le repère du plan de salle, y croît vers le sud)."""
    n = len(phones)
    bx = sum(p[0] for p in phones.values()) / n
    by = sum(p[1] for p in phones.values()) / n
    return CircleTrajectory((bx + east_m, by - north_m, altitude_m), radius_m, period_s)


class ScriptedEstimator:
    def __init__(
        self,
        phones: Mapping[str, Point],
        trajectory: CircleTrajectory,
        detection_range_m: float,
        uncertainty_rel: float,
    ) -> None:
        self._phones = dict(phones)
        self._trajectory = trajectory
        self._detection_range_m = detection_range_m
        self._uncertainty_rel = uncertainty_rel

    def drone_position(self, t: float) -> Point:
        """Position vraie du drone virtuel : sert uniquement à vérifier la chaîne (affichage)."""
        return self._trajectory.position(t)

    def estimate(self, window: AudioWindow) -> DistanceEstimate:
        distance = math.dist(self.drone_position(window.t), self._phones[window.profile])
        if distance > self._detection_range_m:
            return DistanceEstimate(window.profile, window.t, None)
        return DistanceEstimate(window.profile, window.t, Range(distance, self._uncertainty_rel))
