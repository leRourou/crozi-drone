"""③ branché : combine les distances récentes des téléphones en une zone où se trouve le drone.

Une seule tâche de fond (run_fusion) recalcule la zone toutes les STATE_PERIOD_MS ; localiser_drone
(≈ 60 ms) tourne dans un thread pour ne jamais bloquer la réception audio. La même tâche tient la
piste du drone (Tracker, filtre de Kalman) : seule écrivaine, elle n'a pas besoin de verrou.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from api.settings import Settings
from localization import Mesure, SuiviDrone, Zone, localiser_drone

if TYPE_CHECKING:
    from api.state import PhoneRegistry

Point = tuple[float, float, float]
TruthFn = Callable[[float], Point]  # position vraie du drone simulé, selon l'heure murale

REQUIRED = 3  # localiser_drone a besoin de 3 distances


@dataclass(frozen=True)
class Ranging:
    """Une détection avec distance, prête à être combinée (received_at : horloge monotone)."""

    profile: str
    position: Point
    distance_m: float
    uncertainty_rel: float
    received_at: float


def select(rangings: list[Ranging], now: float, fresh_s: float, spread_s: float) -> list[Ranging]:
    """Détections fraîches, et proches dans le temps de la plus récente : on ne combine pas des
    distances mesurées à des instants trop éloignés (le drone a bougé entre-temps)."""
    fresh = [r for r in rangings if now - r.received_at <= fresh_s]
    if not fresh:
        return []
    newest = max(r.received_at for r in fresh)
    return [r for r in fresh if newest - r.received_at <= spread_s]


def locate(rangings: list[Ranging]) -> dict[str, Any] | None:
    """Zone du drone (repère de la salle, mètres) ou None si les distances sont incompatibles."""
    result = localiser_drone(
        [r.position for r in rangings],
        [r.distance_m for r in rangings],
        tol=max(r.uncertainty_rel for r in rangings),
    )
    if result is None:
        return None
    x, y = result["centre_xy"]
    return {
        "x_m": x,
        "y_m": y,
        "radius_m": result["rayon_xy"],
        "z_m": result["z_est"],
        "z_min_m": result["z_min"],
        "z_max_m": result["z_max"],
        "tolerance": result["tol_utilisee"],
        "degraded": result["degrade"],
    }


class Tracker:
    """Piste du drone d'un tick à l'autre : chaque détection ne corrige la piste qu'une fois."""

    def __init__(self, settings: Settings) -> None:
        self._suivi = SuiviDrone(
            settings.track_accel_std,
            settings.track_timeout_s,
            settings.track_altitude_m,
            settings.track_altitude_std_m,
        )
        self._seen: dict[str, float] = {}  # dernière détection utilisée, par téléphone

    def step(
        self, rangings: list[Ranging], zone: dict[str, Any] | None, now: float
    ) -> dict[str, float] | None:
        """Corrige la piste avec les détections nouvelles ; zone (vue de locate) ne sert qu'à la
        (re)démarrer, et seulement avec des détections nouvelles. Renvoie la piste prédite à now."""
        new = [r for r in rangings if r.received_at > self._seen.get(r.profile, -math.inf)]
        self._seen.update((r.profile, r.received_at) for r in new)
        # Une correction par détection, à son instant : les téléphones ne mesurent pas ensemble.
        for r in sorted(new, key=lambda r: r.received_at):
            mesure = Mesure(r.position, r.distance_m, r.uncertainty_rel)
            self._suivi.mise_a_jour([mesure], r.received_at, _zone(zone))
        return _track_view(self._suivi.etat(now))


def _zone(view: dict[str, Any] | None) -> Zone | None:
    if view is None:
        return None
    return Zone((view["x_m"], view["y_m"]), view["radius_m"], view["z_min_m"], view["z_max_m"])


def _track_view(etat: dict[str, Any] | None) -> dict[str, float] | None:
    if etat is None:
        return None
    x, y, z = etat["position"]
    vx, vy, _ = etat["vitesse"]
    return {
        "x_m": x,
        "y_m": y,
        "z_m": z,
        "vx_mps": vx,
        "vy_mps": vy,
        "radius_m": etat["rayon_xy"],
        "z_min_m": etat["z_min"],
        "z_max_m": etat["z_max"],
    }


def _point_view(point: Point) -> dict[str, float]:
    x, y, z = point
    return {"x_m": x, "y_m": y, "z_m": z}


def _status(detecting: int, zone: dict[str, Any] | None) -> str:
    if detecting == 0:
        return "no_detection"
    if detecting < REQUIRED:
        return "insufficient"
    return "located" if zone is not None else "inconsistent"


async def fuse_once(
    registry: PhoneRegistry,
    settings: Settings,
    truth: TruthFn | None,
    now: float,
    wall: float,
    tracker: Tracker,
) -> None:
    rangings = registry.rangings()
    selected = select(rangings, now, settings.detection_fresh_s, settings.fusion_spread_s)
    zone = await asyncio.to_thread(locate, selected) if len(selected) >= REQUIRED else None
    registry.set_drone(
        {
            "status": _status(len(selected), zone),
            "detecting": len(selected),
            "zone": zone,
            "track": tracker.step(rangings, zone, now),
            "truth": _point_view(truth(wall)) if truth is not None else None,
        },
        now,
    )


async def run_fusion(registry: PhoneRegistry, settings: Settings, truth: TruthFn | None) -> None:
    tracker = Tracker(settings)
    while True:
        await fuse_once(registry, settings, truth, time.monotonic(), time.time(), tracker)
        await asyncio.sleep(settings.state_period_s)
