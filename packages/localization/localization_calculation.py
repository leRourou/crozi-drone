import numpy as np

def localiser_drone(capteurs, distances, tol=0.10, z_sol=0.0,
                    n_xy=80, n_z=40, tol_max=0.5):
    """
    capteurs  : array (3, 3) -> [[x, y, z], ...]
    distances : array (3,)   -> distances estimées par l'IA (mêmes unités)
    tol       : incertitude relative (0.10 = ±10 %)
    z_sol     : altitude minimale possible du drone (lève l'ambiguïté en z)

    Retourne un dict avec :
      centre_xy, rayon_xy : disque englobant en vue de dessus
      z_min, z_max, z_est : plage et estimation d'altitude
      tol_utilisee        : tolérance réellement utilisée
      degrade             : True si la tolérance a dû être élargie
    ou None si aucune zone n'est trouvée.
    """
    C = np.asarray(capteurs, dtype=float)
    d = np.asarray(distances, dtype=float)

    t = tol
    while t <= tol_max:
        lo, hi = d * (1 - t), d * (1 + t)

        # Boîte englobante = intersection des boîtes [Ci ± hi]
        bmin = np.max(C - hi[:, None], axis=0)
        bmax = np.min(C + hi[:, None], axis=0)
        bmin[2] = max(bmin[2], z_sol)

        if np.all(bmin < bmax):
            xs = np.linspace(bmin[0], bmax[0], n_xy)
            ys = np.linspace(bmin[1], bmax[1], n_xy)
            zs = np.linspace(bmin[2], bmax[2], n_z)
            P = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).reshape(-1, 3)

            # distances points <-> capteurs : (N, 3)
            dist = np.linalg.norm(P[:, None, :] - C[None, :, :], axis=2)
            ok = np.all((dist >= lo) & (dist <= hi), axis=1)

            if ok.any():
                Q = P[ok]
                centre = Q[:, :2].mean(axis=0)
                rayon = np.linalg.norm(Q[:, :2] - centre, axis=1).max()
                return {
		    "capteurs": capteurs,
                    "centre_xy": centre.tolist(),
                    "rayon_xy": float(rayon),
                    "z_min": float(Q[:, 2].min()),
                    "z_max": float(Q[:, 2].max()),
                    "z_est": float(Q[:, 2].mean()),
                    "tol_utilisee": t,
                    "degrade": t > tol,
                }
        t *= 1.25  # on élargit si aucune zone compatible

    return None

"""
# Exemple
if __name__ == "__main__":
    capteurs = [[0, 0, 0], [100, 0, 0], [50, 80, 2]]
    distances = [60, 62, 55]
    print(localiser_drone(capteurs, distances))
"""
