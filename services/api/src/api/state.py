"""État général : quels téléphones captent, et ce que ② en déduit (drone détecté, distance).

Registre en mémoire d'un seul processus. Il est modifié uniquement depuis la boucle asyncio :
chaque connexion pilote sa propre PhoneSession, et le registre produit l'instantané diffusé sur
/ws/state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from api.profiles import Profile
from distance_estimation.estimator import DistanceEstimate

STALE_AFTER_S = 1.0  # plus de paquet depuis plus longtemps : réseau qui décroche
DETECTION_FRESH_S = 2.0  # au-delà, une distance n'est plus représentative d'un drone en vol


@dataclass
class _Detection:
    estimate: DistanceEstimate
    received_at: float


class PhoneSession:
    """Poignée d'une session : sans effet dès qu'une session plus récente du même téléphone
    l'a remplacée."""

    def __init__(
        self,
        registry: PhoneRegistry,
        profile: str,
        session_id: str,
        contract: str,
        on_replaced: Callable[[], None],
    ) -> None:
        self._registry = registry
        self.profile = profile
        self.session_id = session_id
        self.contract = contract
        self.on_replaced = on_replaced
        self.rt_ratio: float | None = None
        self.rms_dbfs: float | None = None
        self.detection: _Detection | None = None

    def _current(self) -> bool:
        return self._registry._live.get(self.profile) is self

    def packet(self, now: float) -> None:
        if self._current():
            self._registry._last_seen[self.profile] = now

    def stats(self, rt_ratio: float, rms_dbfs: float | None) -> None:
        self.rt_ratio, self.rms_dbfs = rt_ratio, rms_dbfs

    def estimate(self, estimate: DistanceEstimate, now: float) -> None:
        self.detection = _Detection(estimate, now)

    def end(self, now: float) -> None:
        if self._current():
            del self._registry._live[self.profile]
            self._registry._last_seen[self.profile] = now


def _detection_view(detection: _Detection | None, now: float) -> dict[str, Any] | None:
    if detection is None:
        return None
    rng = detection.estimate.range
    age = now - detection.received_at
    return {
        "drone": rng is not None,
        "distance_m": rng.distance_m if rng else None,
        "uncertainty_rel": rng.uncertainty_rel if rng else None,
        "age_s": age,
        "fresh": age <= DETECTION_FRESH_S,
    }


def _status(session: PhoneSession | None, last_seen: float | None, now: float) -> str:
    if session is not None:
        return "streaming" if now - last_seen <= STALE_AFTER_S else "stale"
    return "never_seen" if last_seen is None else "offline"


class PhoneRegistry:
    def __init__(self, profiles: tuple[Profile, ...], estimator: str) -> None:
        self._profiles = profiles
        self._estimator = estimator
        self._live: dict[str, PhoneSession] = {}
        self._last_seen: dict[str, float] = {}

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(p.id for p in self._profiles)

    def start(
        self,
        profile: str,
        session_id: str,
        contract: str,
        on_replaced: Callable[[], None],
        now: float,
    ) -> PhoneSession:
        """La session la plus récente gagne : l'ancienne est prévenue qu'elle doit s'arrêter."""
        previous = self._live.get(profile)
        if previous is not None:
            previous.on_replaced()
        session = PhoneSession(self, profile, session_id, contract, on_replaced)
        self._live[profile] = session
        self._last_seen[profile] = now
        return session

    def _phone(self, profile: Profile, now: float) -> dict[str, Any]:
        session = self._live.get(profile.id)
        last_seen = self._last_seen.get(profile.id)
        return {
            "profile": profile.id,
            "label": profile.label,
            "position_m": {"x": profile.x_m, "y": profile.y_m, "z": profile.z_m},
            "status": _status(session, last_seen, now),
            "session_id": session.session_id if session else None,
            "contract": session.contract if session else None,
            "last_seen_age_s": now - last_seen if last_seen is not None else None,
            "rt_ratio": session.rt_ratio if session else None,
            "rms_dbfs": session.rms_dbfs if session else None,
            "detection": _detection_view(session.detection, now) if session else None,
        }

    def snapshot(self, now: float, server_time: float) -> dict[str, Any]:
        """now : horloge monotone (âges) ; server_time : epoch affichable."""
        return {
            "type": "state",
            "server_time": server_time,
            "estimator": self._estimator,
            "phones": [self._phone(p, now) for p in self._profiles],
            "drone": None,
        }
