"""Téléphones de l'équipe, lus depuis le contrat partagé contracts/profiles.json.

Seule source de la liste : le front l'importe au build, le serveur la valide ici au démarrage et
transmet aux modules ce dont ils ont besoin (identifiants pour audio-capture, positions plus tard).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Relatif au dossier de lancement (racine du dépôt, /app dans l'image) ; PROFILES_FILE prioritaire.
DEFAULT_PROFILES_FILE = Path("contracts/profiles.json")
_ID = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class Profile:
    """Un téléphone : identifiant ASCII stable, libellé affiché, position en mètres (x ; y ; z)."""

    id: str
    label: str
    x_m: float
    y_m: float
    z_m: float


def _coordinate(position: dict[str, Any], axis: str) -> float:
    value = position.get(axis)
    if type(value) not in (int, float):  # bool exclu
        raise ValueError(f"position_m.{axis} must be a number, got {value!r}")
    return float(value)


def _parse_profile(obj: Any) -> Profile:
    if not isinstance(obj, dict):
        raise ValueError(f"each profile must be an object, got {obj!r}")
    pid, label, position = obj.get("id"), obj.get("label"), obj.get("position_m")
    if not isinstance(pid, str) or not _ID.fullmatch(pid):
        raise ValueError(f"profile id must be lowercase ASCII, got {pid!r}")
    if not isinstance(label, str) or not label:
        raise ValueError(f"profile {pid}: label must be a non-empty string")
    if not isinstance(position, dict):
        raise ValueError(f"profile {pid}: position_m must be an object")
    x, y, z = (_coordinate(position, axis) for axis in "xyz")
    return Profile(pid, label, x, y, z)


def load_profiles(path: Path | None = None) -> tuple[Profile, ...]:
    """Lit et valide le contrat ; lève ValueError (le serveur ne démarre pas) s'il est invalide."""
    path = path or Path(os.environ.get("PROFILES_FILE", DEFAULT_PROFILES_FILE))
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: top level must be an object")
    raw = obj.get("profiles")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path}: profiles must be a non-empty list")
    profiles = tuple(_parse_profile(item) for item in raw)
    ids = [p.id for p in profiles]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate profile id in {ids}")
    return profiles
