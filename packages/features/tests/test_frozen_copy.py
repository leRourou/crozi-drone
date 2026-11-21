"""Garde-fou : dsp.py et ml.py sont des copies figées du repo ML, jamais modifiées à la main.

Mise à jour = nouvelle release ML : recopier les deux fichiers au commit de la release, puis
mettre à jour ces empreintes et PROVENANCE.md ensemble.
"""

import hashlib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
EXPECTED_SHA256 = {  # release edth.audio.48k-w100.r1 (drone_triangularisation_ia @ f6c6ce4)
    "dsp.py": "7510cc2f5826361667f3d718f2b988425a2da5b3c0e0f1aef7d1feab58f26ae8",
    "features.py": "0a364e73e4bfa80901d0a0da2c71efec066a01081c1e7542c2afe8ce77ffef0f",
    "ml.py": "c1a6dd8f41fa05cba55273609d07a54b3a93bff9f0b982e6e033a961c6cc4208",
}


@pytest.mark.parametrize("name", sorted(EXPECTED_SHA256))
def test_frozen_copy_is_the_released_version(name):
    assert hashlib.sha256((SRC / name).read_bytes()).hexdigest() == EXPECTED_SHA256[name]
