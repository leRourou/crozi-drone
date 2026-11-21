"""Bundle de release du modèle (contrat d'intégration ML v2, `edth.model-release.v2`).

Un bundle = manifest.json + frozen/ (dsp.py, features.py, ml.py) + detection/ et
distance/model.joblib + parity/fixture.json. Le chargement valide le manifeste contre la copie
figée (packages/features), charge les pickles (qui référencent le module `ml`), vérifie leurs
colonnes, puis rejoue le lot de parité par le chemin live : tout écart → ValueError, sans repli.
Les features d'une fenêtre sont recalculées par `dsp.window_features` avec les arguments exacts de
`features.recompute` (v2 : features locales de fenêtre uniquement).
Le module lit un dossier local ; le téléchargement (Hugging Face) relève de services/api.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import dsp
import features as frozen_features
import joblib
import ml
import numpy as np
import pandas as pd

from distance_estimation.stream import TRANSPORT_RATE, Ready, Stream, Windowing

CONTRACT = "edth.model-release.v2"
TRANSPORT = {"rate_hz": TRANSPORT_RATE, "format": "pcm_s16le", "channels": 1}
PARITY_FILE = "parity/fixture.json"
# Code figé embarqué par la release : l'appli importe exactement ces fichiers (packages/features).
FROZEN = {f"frozen/{Path(m.__file__).name}": Path(m.__file__) for m in (dsp, frozen_features, ml)}
# Arguments de dsp.window_features que features.recompute peut fixer (window_ms : input.window).
RECOMPUTE_ARGS = frozenset(inspect.signature(dsp.window_features).parameters) - {
    "pcm", "rate", "window_ms"
}
# Parité : features identiques (même code, décimation invariante par blocs) ; scores à l'écart
# flottant près (modèles évalués par lots hors ligne, fenêtre par fenêtre en live).
FEATURE_ATOL, DECISION_ATOL = 1e-9, 1e-6


class Predictor(Protocol):
    def predict(self, d: pd.DataFrame) -> np.ndarray: ...


@dataclass(frozen=True)
class Decision:
    """Sortie des modèles pour une fenêtre valide : distance None sous le seuil de détection."""

    features: Mapping[str, Any]  # sortie de dsp.window_features (une valeur par colonne)
    score: float
    distance_m: float | None


@dataclass(frozen=True)
class Release:
    name: str
    windowing: Windowing
    threshold: float
    detection: Predictor
    distance: Predictor
    window_ms: int
    recompute: Mapping[str, Any]  # arguments de dsp.window_features (manifeste, features.recompute)

    def decide(self, window: np.ndarray) -> Decision:
        features = dsp.window_features(
            window, self.windowing.rate, window_ms=self.window_ms, **self.recompute
        )
        frame = pd.DataFrame([features])
        score = float(self.detection.predict(frame)[0])
        if score < self.threshold:
            return Decision(features, score, None)
        return Decision(features, score, float(self.distance.predict(frame)[0]))


@dataclass(frozen=True)
class _Manifest:
    name: str
    windowing: Windowing
    threshold: float
    detection_file: str
    distance_file: str
    detection_columns: list[str]
    distance_columns: list[str]
    window_ms: int
    recompute: Mapping[str, Any]
    frozen: Mapping[str, Any]


def load_release(root: Path) -> Release:
    root = Path(root)
    manifest = parse_manifest(json.loads(_bundle_file(root, "manifest.json").read_text("utf-8")))
    _check_frozen(root, manifest.frozen)  # avant les pickles : ils exécutent le code de ml.py
    release = Release(
        manifest.name,
        manifest.windowing,
        manifest.threshold,
        _load_model(root, manifest.detection_file, manifest.detection_columns, "detection"),
        _load_model(root, manifest.distance_file, manifest.distance_columns, "distance"),
        manifest.window_ms,
        manifest.recompute,
    )
    check_parity(release, json.loads(_bundle_file(root, PARITY_FILE).read_text("utf-8")))
    return release


def _load_model(root: Path, name: str, columns: list[str], role: str) -> Predictor:
    model = joblib.load(_bundle_file(root, name))
    if list(getattr(model, "cols", [])) != columns:
        raise ValueError(f"manifeste : {role}.columns diffère des colonnes du modèle {name}")
    return model


def _bundle_file(root: Path, name: str) -> Path:
    """Confinement vérifié sur le chemin écrit (pas de « .. » qui sorte du bundle), sans suivre
    les liens : le cache Hugging Face range les fichiers d'un snapshot en liens vers ses blobs."""
    path = Path(os.path.normpath(root / name))
    if not path.is_relative_to(Path(os.path.normpath(root))):
        raise ValueError(f"fichier hors du bundle : {name}")
    if not path.is_file():
        raise ValueError(f"fichier absent du bundle : {name}")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_frozen(root: Path, files: Mapping[str, Any]) -> None:
    for name, app_copy in FROZEN.items():
        if name not in files:
            raise ValueError(f"manifeste : frozen.files ne liste pas {name}")
        if _sha256(_bundle_file(root, name)) != files[name]:
            raise ValueError(f"{name} : empreinte différente de celle du manifeste")
        if _sha256(app_copy) != files[name]:
            raise ValueError(
                f"{name} : la copie figée de l'appli (packages/features) n'est pas celle de la "
                "release ; recopier frozen/ du bundle et mettre à jour ses empreintes"
            )


def _field(data: Mapping[str, Any], dotted: str) -> Any:
    value: Any = data
    for key in dotted.split("."):
        if not isinstance(value, Mapping) or key not in value:
            raise ValueError(f"manifeste : champ manquant {dotted}")
        value = value[key]
    return value


def _samples(ms: Any, rate: int, what: str, minimum: int = 0) -> int:
    """Durée (ms) → nombre entier d'échantillons ≥ minimum ; une garde peut valoir 0, pas un pas."""
    exact = ms * rate / 1000 if type(ms) in (int, float) else None
    if exact is None or exact < minimum or exact != int(exact):
        raise ValueError(
            f"manifeste : {what} = {ms!r} ms, pas un entier d'échantillons ≥ {minimum}"
        )
    return int(exact)


def _fir_sha256(rate: int) -> str | None:
    fir = dsp.antialias_fir(rate)
    return None if fir is None else hashlib.sha256(fir.astype("<f8").tobytes()).hexdigest()


def parse_manifest(data: Mapping[str, Any]) -> _Manifest:
    if _field(data, "contract") != CONTRACT:
        raise ValueError(f"manifeste : contract {data['contract']!r} non supporté ({CONTRACT})")
    if _field(data, "input.transport") != TRANSPORT:
        raise ValueError(f"manifeste : transport attendu {TRANSPORT}")
    rate = _field(data, "input.model_rate_hz")
    if rate not in dsp.RATES:
        raise ValueError(f"manifeste : model_rate_hz {rate!r} inconnu de dsp.py ({dsp.RATES})")
    fir = _field(data, "input.fir")
    if (None if fir is None else _field(fir, "coefficients_sha256")) != _fir_sha256(rate):
        raise ValueError("manifeste : FIR différent de celui de la copie figée de dsp.py")
    return _Manifest(
        name=str(_field(data, "release")),
        windowing=_windowing(data, rate),
        threshold=_threshold(_field(data, "detection.threshold")),
        detection_file=str(_field(data, "detection.file")),
        distance_file=str(_field(data, "distance.file")),
        detection_columns=list(_field(data, "detection.columns")),
        distance_columns=list(_field(data, "distance.columns")),
        window_ms=_field(data, "input.window.ms"),
        recompute=_recompute(data),
        frozen=_field(data, "frozen.files"),
    )


def _recompute(data: Mapping[str, Any]) -> dict[str, Any]:
    if _field(data, "features.local_only") is not True:
        raise ValueError("manifeste : features.local_only doit être vrai (features de fenêtre)")
    recompute = dict(_field(data, "features.recompute"))
    unknown = sorted(set(recompute) - RECOMPUTE_ARGS)
    if unknown:
        raise ValueError(f"manifeste : features.recompute inconnus de window_features {unknown}")
    group = recompute.get("band_level_group")
    if group is not None and group not in dsp.BAND_LEVEL_LAYOUTS:
        raise ValueError(f"manifeste : band_level_group {group!r} inconnu de dsp.py")
    return recompute


def _windowing(data: Mapping[str, Any], rate: int) -> Windowing:
    window = _field(data, "input.window")
    samples = _samples(_field(window, "ms"), rate, "window.ms", minimum=1)
    step = _samples(_field(window, "step_ms"), rate, "window.step_ms", minimum=1)
    if (_field(window, "samples"), _field(window, "step_samples")) != (samples, step):
        raise ValueError("manifeste : window.samples / step_samples incohérents avec les durées")
    start = _samples(_field(data, "input.qc.start_guard_ms"), rate, "qc.start_guard_ms")
    if (start + samples) % step:
        raise ValueError("manifeste : la fin des fenêtres doit tomber sur le pas (start + window)")
    return Windowing(
        rate=rate,
        samples=samples,
        step=step,
        start=start,
        zero_run=_samples(_field(data, "input.qc.zero_run_ms"), TRANSPORT_RATE, "qc.zero_run_ms"),
        guard=_samples(_field(data, "input.qc.guard_ms"), TRANSPORT_RATE, "qc.guard_ms"),
    )


def _threshold(value: Any) -> float:
    if type(value) not in (int, float) or not 0 < value < 1:
        raise ValueError(f"manifeste : detection.threshold {value!r} hors de ]0, 1[")
    return float(value)


def check_parity(release: Release, fixture: Mapping[str, Any]) -> None:
    """Lot de parité de la release : chaque cas est une session (amorce + une fenêtre) rejouée par
    le chemin live, blocs d'un pas, et comparée à la fenêtre calculée hors ligne."""
    cases = _field(fixture, "cases")
    if not cases:
        raise ValueError("parité : lot vide")
    for case in cases:
        problem = _replay_case(release, case)
        if problem is not None:
            raise ValueError(f"parité : {case.get('sample_id', '?')} : {problem}")


def _replay_case(release: Release, case: Mapping[str, Any]) -> str | None:
    excerpt, want = _field(case, "excerpt"), _field(case, "expected")
    pcm = np.frombuffer(base64.b64decode(_field(excerpt, "pcm48_b64")), "<i2")
    chunk = release.windowing.chunk_frames
    if len(pcm) % chunk:
        return f"extrait de {len(pcm)} échantillons, pas un multiple du bloc ({chunk})"
    stream = Stream(release.windowing)
    last = [stream.push(pcm[i : i + chunk]) for i in range(0, len(pcm), chunk)][-1]
    if not isinstance(last, Ready) or last.start != _field(excerpt, "window_start_offset"):
        return f"le chemin live ne produit pas la fenêtre attendue ({last})"
    if last.pcm.astype("<i2").tobytes() != base64.b64decode(_field(want, "window_pcm_b64")):
        return "fenêtre (après décimation) différente"
    if (_field(want, "window_ms"), _field(want, "recompute")) != (
        release.window_ms, dict(release.recompute)
    ):
        return "recette de features différente de celle du manifeste"
    got = release.decide(last.pcm)
    return None if _same(got, want) else f"décision différente (score live {got.score})"


def _same(got: Decision, want: Mapping[str, Any]) -> bool:
    expected = want["flat"]
    if set(expected) - set(got.features):
        return False
    flat = [got.features[c] for c in expected]
    if not np.allclose(flat, list(expected.values()), rtol=0, atol=FEATURE_ATOL):
        return False
    if abs(got.score - want["score"]) > DECISION_ATOL:
        return False
    if (got.distance_m is not None) != want["present"]:
        return False
    return got.distance_m is None or abs(got.distance_m - want["distance_m"]) <= DECISION_ATOL
