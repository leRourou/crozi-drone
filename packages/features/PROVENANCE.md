# Provenance de la copie figée

Contrat d'intégration ML v2 (§3) : le code d'inférence de la release vit ici tel quel, importable sous
les noms `dsp`, `features` et `ml` (les pickles joblib référencent `ml.Mlp`, `ml.CnnPresence`).
Ne jamais modifier à la main ; `tests/test_frozen_copy.py` vérifie les empreintes, et le chargeur
refuse une release dont `manifest.frozen.files` ne correspond pas à ces fichiers.

Release : `edth.audio.48k-w100.r1` (repo HF `ImAPancake/EDTH_ml_models`, révision
`e7a6a5444bb72f08ee9c7dfea00fe78e5a9fbee7`), code au commit ML `f6c6ce40243abc299a3ab64b81ae9537f24dfa90`.

| Fichier | Origine (bundle) | SHA-256 |
|---|---|---|
| `src/dsp.py` | `frozen/dsp.py` | `7510cc2f5826361667f3d718f2b988425a2da5b3c0e0f1aef7d1feab58f26ae8` |
| `src/features.py` | `frozen/features.py` | `0a364e73e4bfa80901d0a0da2c71efec066a01081c1e7542c2afe8ce77ffef0f` |
| `src/ml.py` | `frozen/ml.py` | `c1a6dd8f41fa05cba55273609d07a54b3a93bff9f0b982e6e033a961c6cc4208` |

Nouvelle release : recopier son `frozen/` ici, mettre à jour ce tableau et les empreintes du test dans
le même commit ; le démarrage rejoue ensuite son lot de parité.
