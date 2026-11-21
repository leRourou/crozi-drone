# Provenance de la copie figée

Contrat d'intégration ML V1 (§3) : le prétraitement et les modèles de la release vivent ici tels quels,
importables sous les noms `dsp` et `ml` (les pickles joblib référencent `ml.CnnPresence`, `ml.Mlp`).
Ne jamais modifier à la main ; le test `tests/test_frozen_copy.py` vérifie les empreintes.

| Fichier | Origine (drone_triangularisation_ia) | Commit | SHA-256 |
|---|---|---|---|
| `src/dsp.py` | `01_ppc_features/dsp.py` | `ec518233128d99f83acac6fa3c9dd8581220f210` | `4d5f6eb3a31cd8d5a96a23b27092c2fdc5ea063e1e7e44f4e12ba1349a59f7e3` |
| `src/ml.py` | `ml.py` | `ec518233128d99f83acac6fa3c9dd8581220f210` | `7822c2b219b62d768c423989938107a5bfa0c0b505313b6ce135cd40a9392cf6` |

Nouvelle release : recopier les deux fichiers au commit de la release, mettre à jour ce tableau et les
empreintes du test dans le même commit, puis vérifier la parité (lot `parity/` de la release).
