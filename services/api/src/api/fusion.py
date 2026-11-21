"""③ branché : combine les distances récentes des téléphones en une zone où se trouve le drone.

Une seule tâche de fond (run_fusion) recalcule la zone toutes les STATE_PERIOD_MS ; localiser_drone
(≈ 60 ms) tourne dans un thread pour ne jamais bloquer la réception audio.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from api.settings import Settings
from localization import localiser_drone

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
    registry: PhoneRegistry, settings: Settings, truth: TruthFn | None, now: float, wall: float
) -> None:
    selected = select(
        registry.rangings(), now, settings.detection_fresh_s, settings.fusion_spread_s
    )
    zone = await asyncio.to_thread(locate, selected) if len(selected) >= REQUIRED else None
    registry.set_drone(
        {
            "status": _status(len(selected), zone),
            "detecting": len(selected),
            "zone": zone,
            "truth": _point_view(truth(wall)) if truth is not None else None,
        },
        now,
    )


async def run_fusion(registry: PhoneRegistry, settings: Settings, truth: TruthFn | None) -> None:
    while True:
        await fuse_once(registry, settings, truth, time.monotonic(), time.time())
        await asyncio.sleep(settings.state_period_s)
