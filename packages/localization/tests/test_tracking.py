"""Suivi du drone (EKF sur les distances) : lissage, rejet des aberrations, perte de la piste."""

import math
import random

import pytest

import numpy as np

from localization import Mesure, SuiviDrone, Zone
from localization.tracking import _transition

CAPTEURS = [(2.06, 9.66, 0.0), (4.0, 10.76, 0.0), (2.06, 11.86, 0.0)]
DRONE = (3.0, 8.0, 1.5)


def mesures(position, capteurs=CAPTEURS, incertitude=0.1, bruit=None):
    out = []
    for c in capteurs:
        d = math.dist(position, c)
        if bruit is not None:
            d *= 1 + bruit.gauss(0.0, incertitude / 2)
        out.append(Mesure(c, d, incertitude))
    return out


def zone_autour(position, rayon=0.5, demi_hauteur=0.5):
    x, y, z = position
    return Zone((x, y), rayon, max(0.0, z - demi_hauteur), z + demi_hauteur)


def suivi(accel_std=1.0, delai_perte_s=3.0, altitude_m=1.5, altitude_std_m=0.5):
    return SuiviDrone(accel_std, delai_perte_s, altitude_m, altitude_std_m)


def ecart_xy(etat, position):
    return math.dist(etat["position"][:2], position[:2])


def test_no_track_before_a_zone_is_given():
    s = suivi()
    s.mise_a_jour(mesures(DRONE), t=0.0, zone=None)
    assert s.etat(0.0) is None


def test_the_track_starts_at_the_zone():
    s = suivi()
    s.mise_a_jour(mesures(DRONE), t=0.0, zone=zone_autour((3.2, 8.1, 1.5)))
    etat = s.etat(0.0)
    assert etat["position"] == pytest.approx([3.2, 8.1, 1.5])
    assert etat["vitesse"] == [0.0, 0.0, 0.0]
    assert etat["rayon_xy"] == pytest.approx(0.5)
    assert (etat["z_min"], etat["z_max"]) == pytest.approx((1.0, 2.0))
    assert etat["mesure_rejetee"] is False


def test_without_distance_the_uncertainty_grows_as_the_motion_model_says():
    s = suivi(accel_std=1.0)
    s.mise_a_jour([], t=0.0, zone=zone_autour(DRONE, rayon=0.4, demi_hauteur=0.5))
    # σ² position : initial 0,2² + vitesse inconnue 2² · dt² + accélération 1² · dt⁴ / 4
    etat = s.etat(1.0)
    assert etat["rayon_xy"] == pytest.approx(2 * np.sqrt(0.04 + 4.0 + 0.25))
    assert etat["z_max"] - 1.5 == pytest.approx(2 * np.sqrt(0.0625 + 4.0 + 0.25))


def test_the_motion_model_is_constant_speed_with_piecewise_constant_acceleration():
    dt, accel_std = 0.5, 2.0
    F, Q = _transition(dt, accel_std)
    one_axis_f = np.array([[1.0, dt], [0.0, 1.0]])
    g = np.array([dt**2 / 2, dt])  # effet d'une accélération constante pendant dt
    for axis in range(3):
        idx = np.ix_([axis, axis + 3], [axis, axis + 3])
        np.testing.assert_allclose(F[idx], one_axis_f)
        np.testing.assert_allclose(Q[idx], accel_std**2 * np.outer(g, g))
    assert np.count_nonzero(F) == 9 and np.count_nonzero(Q) == 12  # axes indépendants


def test_exact_distances_pull_a_static_track_onto_the_drone():
    s = suivi()
    s.mise_a_jour(mesures(DRONE), t=0.0, zone=zone_autour((3.4, 8.3, 1.5)))
    for k in range(1, 40):
        s.mise_a_jour(mesures(DRONE), t=k * 0.25, zone=None)
    sans_mesure = suivi()
    sans_mesure.mise_a_jour([], t=0.0, zone=zone_autour((3.4, 8.3, 1.5)))
    etat = s.etat(10.0)
    assert ecart_xy(etat, DRONE) < 0.05
    assert etat["rayon_xy"] < sans_mesure.etat(2.9)["rayon_xy"]


def test_a_moving_drone_is_followed_and_its_speed_estimated():
    bruit = random.Random(1)
    vitesse = (0.2, -0.1, 0.0)  # reste à portée de la géométrie des téléphones

    def position(t):
        return tuple(p + v * t for p, v in zip(DRONE, vitesse, strict=True))

    s = suivi()
    s.mise_a_jour(mesures(position(0.0)), t=0.0, zone=zone_autour(position(0.0)))
    for k in range(1, 40):
        t = k * 0.25
        s.mise_a_jour(mesures(position(t), bruit=bruit), t=t, zone=None)
    etat = s.etat(10.0)
    assert ecart_xy(etat, position(10.0)) < etat["rayon_xy"]  # la vérité est dans le disque
    vx, vy = etat["vitesse"][:2]
    assert vx > 0 and vy < 0


def test_one_or_two_phones_still_update_the_track():
    s = suivi()
    s.mise_a_jour(mesures(DRONE), t=0.0, zone=zone_autour((3.4, 8.3, 1.5)))
    for k in range(1, 40):
        un_seul = [CAPTEURS[k % 3]]
        s.mise_a_jour(mesures(DRONE, capteurs=un_seul), t=k * 0.25, zone=None)
    assert ecart_xy(s.etat(10.0), DRONE) < 0.1


def test_the_state_is_predicted_at_the_asked_time_without_being_changed():
    s = suivi()
    s.mise_a_jour(mesures(DRONE), t=0.0, zone=zone_autour(DRONE))
    avant = s.etat(0.0)
    plus_tard = s.etat(2.0)
    assert plus_tard["rayon_xy"] > avant["rayon_xy"]  # l'incertitude croît sans mesure
    assert s.etat(0.0) == avant


def converged(t_fin=10.0):
    s = suivi()
    s.mise_a_jour(mesures(DRONE), t=0.0, zone=zone_autour(DRONE))
    t = 0.0
    while t < t_fin:
        t += 0.25
        s.mise_a_jour(mesures(DRONE), t=t, zone=None)
    return s, t


def test_an_aberrant_distance_is_rejected():
    s, t = converged()
    aberrante = [Mesure(CAPTEURS[0], 2 * math.dist(DRONE, CAPTEURS[0]), 0.1)]
    s.mise_a_jour(aberrante, t=t + 0.25, zone=None)
    etat = s.etat(t + 0.25)
    assert etat["mesure_rejetee"] is True
    assert ecart_xy(etat, DRONE) < 0.05


def test_an_accepted_distance_clears_the_rejection_flag():
    s, t = converged()
    s.mise_a_jour([Mesure(CAPTEURS[0], 20.0, 0.1)], t=t + 0.25, zone=None)
    s.mise_a_jour(mesures(DRONE), t=t + 0.5, zone=None)
    assert s.etat(t + 0.5)["mesure_rejetee"] is False


def test_five_rejections_in_a_row_restart_the_track_from_the_zone():
    s, t = converged()
    ailleurs = (1.0, 6.0, 1.0)
    for k in range(1, 6):
        s.mise_a_jour(mesures(ailleurs), t=t + k * 0.25, zone=zone_autour(ailleurs))
    etat = s.etat(t + 1.25)
    assert ecart_xy(etat, ailleurs) < 0.01
    assert etat["mesure_rejetee"] is False


def test_rejections_without_a_zone_keep_the_track():
    s, t = converged()
    ailleurs = (1.0, 6.0, 1.0)
    for k in range(1, 6):
        s.mise_a_jour(mesures(ailleurs), t=t + k * 0.25, zone=None)
    assert ecart_xy(s.etat(t + 1.25), DRONE) < 0.05


def test_the_track_is_lost_without_accepted_distance_for_too_long():
    s, t = converged()
    assert s.etat(t + 3.0) is not None
    assert s.etat(t + 3.01) is None
    s.mise_a_jour(mesures(DRONE), t=t + 3.5, zone=None)
    assert s.etat(t + 3.5) is None  # perdue : seule une zone la relance


def test_a_lost_track_restarts_from_a_new_zone():
    s, t = converged()
    ailleurs = (1.0, 6.0, 1.0)
    s.mise_a_jour(mesures(ailleurs), t=t + 4.0, zone=zone_autour(ailleurs))
    assert ecart_xy(s.etat(t + 4.0), ailleurs) < 0.01


def test_the_altitude_never_goes_below_the_ground():
    bruit = random.Random(2)
    au_sol = (3.0, 8.0, 0.0)
    s = suivi(altitude_m=0.0)  # drone attendu au sol : la butée est atteinte
    s.mise_a_jour(mesures(au_sol), t=0.0, zone=zone_autour(au_sol))
    for k in range(1, 80):
        s.mise_a_jour(mesures(au_sol, bruit=bruit), t=k * 0.25, zone=None)
        etat = s.etat(k * 0.25)
        assert etat["position"][2] >= 0.0
        assert etat["vitesse"][2] >= 0.0 or etat["position"][2] > 0.0
    assert etat["position"][2] < 0.3 and etat["z_min"] == 0.0


def test_the_altitude_leans_towards_the_expected_one():
    """Téléphones coplanaires : les distances disent peu de z, l'altitude attendue complète."""
    altitudes = {}
    for attendue in (1.0, 2.0):
        bruit = random.Random(3)
        s = suivi(altitude_m=attendue)
        s.mise_a_jour(mesures(DRONE), t=0.0, zone=zone_autour(DRONE))
        for k in range(1, 40):
            s.mise_a_jour(mesures(DRONE, bruit=bruit), t=k * 0.25, zone=None)
        altitudes[attendue] = s.etat(10.0)["position"][2]
    assert altitudes[1.0] < DRONE[2] < altitudes[2.0]
