"""Garde-fou : le module de capture partagé n'est jamais modifié sans revalidation volontaire."""

import hashlib
from pathlib import Path

MODULE = Path(__file__).resolve().parents[3] / "vendor" / "edth" / "audio_capture.js"
EXPECTED_SHA256 = "77d337fd2aa374e173379f97688137f1127a019208349f91fec9008fd08a6aeb"  # 2026-11-20


def test_shared_capture_module_is_the_validated_version():
    assert hashlib.sha256(MODULE.read_bytes()).hexdigest() == EXPECTED_SHA256
