"""Garde-fou : dsp.py et ml.py sont des copies figées du repo ML, jamais modifiées à la main.

Mise à jour = nouvelle release ML : recopier les deux fichiers au commit de la release, puis
mettre à jour ces empreintes et PROVENANCE.md ensemble.
"""

import hashlib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
EXPECTED_SHA256 = {  # drone_triangularisation_ia @ ec51823
    "dsp.py": "4d5f6eb3a31cd8d5a96a23b27092c2fdc5ea063e1e7e44f4e12ba1349a59f7e3",
    "ml.py": "7822c2b219b62d768c423989938107a5bfa0c0b505313b6ce135cd40a9392cf6",
}


@pytest.mark.parametrize("name", sorted(EXPECTED_SHA256))
def test_frozen_copy_is_the_released_version(name):
    assert hashlib.sha256((SRC / name).read_bytes()).hexdigest() == EXPECTED_SHA256[name]
