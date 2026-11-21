"""Suivi du drone : filtre de Kalman étendu sur les distances, modèle à vitesse constante.

D'après le SuiviDrone écrit par un ami de l'équipe, adapté au temps réel : les distances arrivent
par téléphone, à des instants différents, parfois une ou deux seulement ; chacune a sa propre
incertitude ; la piste se perd sans distance acceptée pendant delai_perte_s, ou dès que son rayon
dépasse rayon_max_m (un seul téléphone situe le drone sur un cercle, pas le long de ce cercle :
mesuré, 1,8 m d'erreur pour 2,7 m de rayon ; on n'affiche pas un point qui ne dit plus rien).
Une piste naît provisoire (une zone brute dépasse souvent rayon_max_m) : cachée tant qu'elle est
trop large, confirmée dès qu'elle passe sous rayon_max_m ; seule une piste confirmée est abandonnée.

État : [x, y, z, vx, vy, vz] (repère de la salle, mètres). Mesure : distance capteur ↔ drone,
h(p) = ‖p − C‖, linéarisée autour de l'état courant (d'où « étendu »).
Incertitude relative d'une distance = borne à ≈ 2 σ (comme la tol de localiser_drone).

Altitude : les téléphones sont coplanaires (z = 0), les distances disent donc peu de z, et une
erreur sur z se reporte en xy. Chaque correction ajoute une pseudo-mesure z ≈ altitude_m
(écart-type altitude_std_m) : sans elle, la piste diverge (mesuré : 2,4 m d'erreur contre 0,26 m).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

Point = tuple[float, float, float]

# Seuil de rejet à 99 % : χ² à 2 degrés de liberté (une distance + la pseudo-mesure d'altitude).
CHI2_99 = 9.21
NB_REJETS_REINIT = 5  # rejets consécutifs avant de repartir de la zone de localiser_drone
N_SIGMA = 2.0  # rayon affiché = N_SIGMA écarts-types
SIGMA_MIN_M = 0.1  # plancher d'incertitude initiale (une zone de grille peut se réduire à un point)
SIGMA_VITESSE_INIT = 2.0  # m/s : vitesse initiale inconnue, à l'échelle d'un drone en salle
Z_SOL = 0.0  # altitude minimale possible (sol de la salle)


@dataclass(frozen=True)
class Mesure:
    capteur: Point
    distance_m: float
    incertitude_rel: float  # borne relative à ≈ 2 σ
    t: float  # instant de la mesure (s, même horloge que la piste)


@dataclass(frozen=True)
class Zone:
    """Sortie de localiser_drone utile à l'initialisation de la piste."""

    centre_xy: tuple[float, float]
    rayon_xy: float
    z_min: float
    z_max: float


def _transition(dt: float, accel_std: float) -> tuple[np.ndarray, np.ndarray]:
    """F et Q du modèle à vitesse constante, accélération constante par morceaux."""
    F = np.eye(6)
    F[0, 3] = F[1, 4] = F[2, 5] = dt
    q = accel_std**2
    Q = np.zeros((6, 6))
    for i in range(3):
        Q[i, i] = q * dt**4 / 4
        Q[i, i + 3] = Q[i + 3, i] = q * dt**3 / 2
        Q[i + 3, i + 3] = q * dt**2
    return F, Q


def _rayon(P: np.ndarray) -> float:
    """Rayon du disque horizontal à N_SIGMA écarts-types (grand axe de l'ellipse)."""
    return N_SIGMA * float(np.sqrt(np.max(np.linalg.eigvalsh(P[:2, :2]))))


class SuiviDrone:
    """Piste du drone. Un seul écrivain : la tâche de fusion qui l'appelle à chaque tick."""

    def __init__(
        self,
        accel_std: float,
        delai_perte_s: float,
        altitude_m: float,
        altitude_std_m: float,
        rayon_max_m: float,
    ) -> None:
        """accel_std : accélération non modélisée (m/s²) ; grand = suit les manœuvres, petit =
        lisse davantage. altitude_m ± altitude_std_m : altitude attendue du drone. rayon_max_m :
        au-delà, la piste est abandonnée."""
        self.accel_std = accel_std
        self.delai_perte_s = delai_perte_s
        self.altitude_m = altitude_m
        self.altitude_std_m = altitude_std_m
        self.rayon_max_m = rayon_max_m
        self.x: np.ndarray | None = None
        self.P = np.zeros((6, 6))
        self.t = 0.0  # instant de l'état
        self.t_correction = 0.0  # dernière distance acceptée (ou initialisation)
        self._rejets = 0
        self._confirmee = False

    def mise_a_jour(self, mesures: Sequence[Mesure], t: float, zone: Zone | None) -> None:
        """Un tick : intègre les distances nouvelles (datées, ≤ t) chacune à son instant, puis
        juge la piste à t. zone : localisation par grille du tick, ou None ; elle ne sert qu'à
        (re)démarrer la piste."""
        for mesure in sorted(mesures, key=lambda m: m.t):
            self._integrer(mesure, zone)
        self._juger(t)

    def _integrer(self, mesure: Mesure, zone: Zone | None) -> None:
        if self._expiree(mesure.t):
            if zone is not None:
                self._initialiser(zone, mesure.t)
            return
        self._predire(mesure.t)
        self._corriger(mesure)
        if self._rejets >= NB_REJETS_REINIT and zone is not None:
            self._initialiser(zone, mesure.t)

    def _juger(self, t: float) -> None:
        """Une fois par tick, avec toutes ses distances : confirmée sous rayon_max_m, abandonnée
        si une piste confirmée le dépasse (seule une zone la relance ensuite)."""
        if self._expiree(t):
            return
        if _rayon(self._prediction(t)[1]) <= self.rayon_max_m:
            self._confirmee = True
        elif self._confirmee:
            self.x = None

    def etat(self, t: float) -> dict | None:
        """Piste prédite à l'instant t (sans la modifier), ou None si elle est perdue."""
        if self._perdue(t):
            return None
        x, P = self._prediction(t)
        sig_z = float(np.sqrt(P[2, 2]))
        z = float(x[2])
        return {
            "position": x[:3].tolist(),
            "vitesse": x[3:].tolist(),
            "rayon_xy": _rayon(P),
            "z_min": max(Z_SOL, z - N_SIGMA * sig_z),
            "z_max": z + N_SIGMA * sig_z,
            "mesure_rejetee": self._rejets > 0,
        }

    def _expiree(self, t: float) -> bool:
        return self.x is None or t - self.t_correction > self.delai_perte_s

    def _perdue(self, t: float) -> bool:
        """Pour l'affichage : expirée, ou trop large à l'instant t (provisoire ou en train de se
        perdre)."""
        return self._expiree(t) or _rayon(self._prediction(t)[1]) > self.rayon_max_m

    def _prediction(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        """État prédit à t ; jamais à rebours (une distance plus ancienne s'applique à self.t)."""
        F, Q = _transition(max(t - self.t, 0.0), self.accel_std)
        return F @ self.x, F @ self.P @ F.T + Q

    def _initialiser(self, zone: Zone, t: float) -> None:
        sig_xy = max(zone.rayon_xy / N_SIGMA, SIGMA_MIN_M)
        sig_z = max((zone.z_max - zone.z_min) / (2 * N_SIGMA), SIGMA_MIN_M)
        cx, cy = zone.centre_xy
        self.x = np.array([cx, cy, (zone.z_min + zone.z_max) / 2, 0.0, 0.0, 0.0])
        self.P = np.diag([sig_xy**2, sig_xy**2, sig_z**2] + [SIGMA_VITESSE_INIT**2] * 3)
        self.t = self.t_correction = t
        self._rejets = 0
        self._confirmee = False

    def _predire(self, t: float) -> None:
        self.x, self.P = self._prediction(t)
        self.t = max(self.t, t)

    def _corriger(self, mesure: Mesure) -> None:
        diff = self.x[:3] - np.asarray(mesure.capteur, dtype=float)
        h = max(float(np.linalg.norm(diff)), 1e-6)  # distance prédite
        sigma = mesure.incertitude_rel / N_SIGMA * mesure.distance_m
        H = np.zeros((2, 6))
        H[0, :3] = diff / h  # jacobienne de la distance
        H[1, 2] = 1.0  # pseudo-mesure d'altitude
        R = np.diag([sigma**2, self.altitude_std_m**2])
        y = np.array([mesure.distance_m - h, self.altitude_m - self.x[2]])  # innovation
        S_inv = np.linalg.inv(H @ self.P @ H.T + R)
        if float(y @ S_inv @ y) > CHI2_99:  # mesure aberrante
            self._rejets += 1
            return
        K = self.P @ H.T @ S_inv
        self.x = self.x + K @ y
        I_KH = np.eye(6) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T  # forme de Joseph
        self._borner_altitude()
        self.t_correction = self.t  # instant où la distance a été appliquée
        self._rejets = 0

    def _borner_altitude(self) -> None:
        """Téléphones coplanaires → z ambigu en signe : on garde le drone au-dessus du sol."""
        if self.x[2] < Z_SOL:
            self.x[2] = Z_SOL
            self.x[5] = max(self.x[5], 0.0)
