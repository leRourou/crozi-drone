import sys
from pathlib import Path

# Ajoute packages/localization/src au chemin de recherche des modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from localization_calculation import localiser_drone

import time
import unittest

import numpy as np

CAPTEURS = np.array([[0, 0, 0], [100, 0, 0], [50, 80, 2]], dtype=float)
DRONE = np.array([40.0, 30.0, 25.0])


def distances_exactes(capteurs, point):
    return np.linalg.norm(np.asarray(capteurs) - np.asarray(point), axis=1)


class TestLocaliserDrone(unittest.TestCase):

    def assert_resultats_egaux(self, r1, r2):
        self.assertEqual(set(r1), set(r2))
        for cle in r1:
            np.testing.assert_allclose(
                np.asarray(r1[cle], dtype=float),
                np.asarray(r2[cle], dtype=float),
                err_msg=f"Différence sur la clé '{cle}'",
            )

    def test_structure_du_resultat(self):
        res = localiser_drone(CAPTEURS, distances_exactes(CAPTEURS, DRONE))
        self.assertIsNotNone(res)
        cles = {"capteurs", "centre_xy", "rayon_xy", "z_min", "z_max", "z_est",
                "tol_utilisee", "degrade"}
        self.assertEqual(set(res), cles)
        self.assertEqual(len(res["centre_xy"]), 2)

    def test_coherence_interne(self):
        res = localiser_drone(CAPTEURS, distances_exactes(CAPTEURS, DRONE))
        self.assertGreaterEqual(res["rayon_xy"], 0)
        self.assertLessEqual(res["z_min"], res["z_est"])
        self.assertLessEqual(res["z_est"], res["z_max"])

    def test_distances_exactes_position_vraie_dans_la_zone(self):
        res = localiser_drone(CAPTEURS, distances_exactes(CAPTEURS, DRONE))
        ecart_xy = np.linalg.norm(np.array(res["centre_xy"]) - DRONE[:2])
        # marge = pas de grille (la grille est discrète)
        self.assertLessEqual(ecart_xy, res["rayon_xy"] + 1.0)
        self.assertLessEqual(res["z_min"] - 2.0, DRONE[2])
        self.assertGreaterEqual(res["z_max"] + 2.0, DRONE[2])

    def test_distances_bruitees_dans_la_tolerance(self):
        # erreurs de +8 %, -8 %, +5 % : la vraie position doit rester dans la zone
        d = distances_exactes(CAPTEURS, DRONE) * np.array([1.08, 0.92, 1.05])
        res = localiser_drone(CAPTEURS, d)
        self.assertIsNotNone(res)
        self.assertFalse(res["degrade"])
        ecart_xy = np.linalg.norm(np.array(res["centre_xy"]) - DRONE[:2])
        self.assertLessEqual(ecart_xy, res["rayon_xy"] + 1.0)

    def test_z_sol_respecte(self):
        res = localiser_drone(CAPTEURS, distances_exactes(CAPTEURS, DRONE),
                              z_sol=10.0)
        self.assertGreaterEqual(res["z_min"], 10.0)

    def test_tolerance_plus_grande_zone_plus_grande(self):
        d = distances_exactes(CAPTEURS, DRONE)
        petit = localiser_drone(CAPTEURS, d, tol=0.05)
        grand = localiser_drone(CAPTEURS, d, tol=0.15)
        self.assertGreater(grand["rayon_xy"], petit["rayon_xy"])
        self.assertGreater(grand["z_max"] - grand["z_min"],
                           petit["z_max"] - petit["z_min"])

    def test_aucune_degradation_si_mesures_coherentes(self):
        res = localiser_drone(CAPTEURS, distances_exactes(CAPTEURS, DRONE))
        self.assertFalse(res["degrade"])
        self.assertEqual(res["tol_utilisee"], 0.10)

    def test_mesures_incoherentes_elargissement_de_la_tolerance(self):
        # Capteurs 1 et 2 distants de 100 : avec d = 40 chacun, 44 + 44 < 100,
        # donc aucune solution à ±10 %, mais une solution existe à ~30 %.
        capteurs = [[0, 0, 0], [100, 0, 0], [50, 30, 0]]
        res = localiser_drone(capteurs, [40, 40, 40])
        self.assertIsNotNone(res)
        self.assertTrue(res["degrade"])
        self.assertGreater(res["tol_utilisee"], 0.10)
        self.assertLessEqual(res["tol_utilisee"], 0.5)

    def test_aucune_solution_retourne_none(self):
        # capteurs très éloignés, distances minuscules : zones disjointes
        capteurs = [[0, 0, 0], [100, 0, 0], [50, 80, 0]]
        self.assertIsNone(localiser_drone(capteurs, [1, 1, 1]))

    def test_entrees_listes_ou_tableaux_equivalentes(self):
        d = distances_exactes(CAPTEURS, DRONE)
        r1 = localiser_drone(CAPTEURS.tolist(), d.tolist())
        r2 = localiser_drone(CAPTEURS, d)
        self.assert_resultats_egaux(r1, r2)

    def test_determinisme(self):
        d = distances_exactes(CAPTEURS, DRONE)
        self.assertEqual(localiser_drone(CAPTEURS, d),
                         localiser_drone(CAPTEURS, d))

    def test_invariance_par_translation(self):
        d = distances_exactes(CAPTEURS, DRONE)
        decalage = np.array([1000.0, -500.0, 0.0])
        r1 = localiser_drone(CAPTEURS, d)
        r2 = localiser_drone(CAPTEURS + decalage, d)
        np.testing.assert_allclose(
            np.array(r2["centre_xy"]) - decalage[:2], r1["centre_xy"], atol=1e-6)
        self.assertAlmostEqual(r1["rayon_xy"], r2["rayon_xy"], places=6)

    def test_performance_temps_reel(self):
        d = distances_exactes(CAPTEURS, DRONE)
        t0 = time.perf_counter()
        for _ in range(5):
            localiser_drone(CAPTEURS, d)
        moyenne = (time.perf_counter() - t0) / 5
        self.assertLess(moyenne, 0.5)  # seuil large, à ajuster selon ton besoin


if __name__ == "__main__":
    unittest.main()