"""Bundle de release du modèle (contrat d'intégration ML V1, `edth.model-release.v1`).

Un bundle = manifest.json + detection/ et distance/model.joblib + parity/fixture.json. Le chargement
valide le manifeste contre la copie figée de dsp.py, charge les pickles (qui référencent le module
`ml`), puis rejoue le lot de parité par le chemin live : tout écart → ValueError, jamais de repli.
Le module lit un dossier local ; le téléchargement (Hugging Face) relève de services/api.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import dsp
import joblib
import ml
import numpy as np
import pandas as pd

from distance_estimation.stream import TRANSPORT_RATE, Ready, Stream, Windowing

CONTRACT = "edth.model-release.v1"
TRANSPORT = {"rate_hz": TRANSPORT_RATE, "format": "pcm_s16le", "channels": 1}
PARITY_FILE = "parity/fixture.json"
# Code figé embarqué par la release : l'appli importe exactement ces fichiers (packages/features).
FROZEN = {"frozen/dsp.py": Path(dsp.__file__), "frozen/ml.py": Path(ml.__file__)}
# Parité : features identiques (même code, décimation invariante par blocs) ; scores à l'écart
# flottant près (le CNN est évalué par lots hors ligne, fenêtre par fenêtre en live).
FEATURE_ATOL, DECISION_ATOL = 1e-9, 1e-6


class Predictor(Protocol):
    def predict(self, d: pd.DataFrame) -> np.ndarray: ...


@dataclass(frozen=True)
class Decision:
    """Sortie des modèles pour une fenêtre valide : distance None sous le seuil de détection."""

    flat: tuple[float, ...]
    score: float
    distance_m: float | None


@dataclass(frozen=True)
class Release:
    name: str
    windowing: Windowing
    threshold: float
    detection: Predictor
    distance: Predictor

    def decide(self, window: np.ndarray) -> Decision:
        features = dsp.window_features(window, self.windowing.rate)
        frame = pd.DataFrame([features])
        flat = tuple(float(features[c]) for c in dsp.FLAT_COLS)
        score = float(self.detection.predict(frame)[0])
        if score < self.threshold:
            return Decision(flat, score, None)
        return Decision(flat, score, float(self.distance.predict(frame)[0]))


@dataclass(frozen=True)
class _Manifest:
    name: str
    windowing: Windowing
    threshold: float
    detection_file: str
    distance_file: str
    frozen: Mapping[str, Any]


def load_release(root: Path) -> Release:
    root = Path(root)
    manifest = parse_manifest(json.loads(_bundle_file(root, "manifest.json").read_text("utf-8")))
    _check_frozen(root, manifest.frozen)  # avant les pickles : ils exécutent le code de ml.py
    release = Release(
        manifest.name,
        manifest.windowing,
        manifest.threshold,
        joblib.load(_bundle_file(root, manifest.detection_file)),
        joblib.load(_bundle_file(root, manifest.distance_file)),
    )
    check_parity(release, json.loads(_bundle_file(root, PARITY_FILE).read_text("utf-8")))
    return release


def _bundle_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
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
    if _field(data, "input.fir.coefficients_sha256") != _fir_sha256(rate):
        raise ValueError("manifeste : empreinte FIR différente de la copie figée de dsp.py")
    return _Manifest(
        name=str(_field(data, "release")),
        windowing=_windowing(data, rate),
        threshold=_threshold(_field(data, "detection.threshold")),
        detection_file=str(_field(data, "detection.file")),
        distance_file=str(_field(data, "distance.file")),
        frozen=_field(data, "frozen.files"),
    )


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
    """Rejoue le PCM48 du lot par blocs d'un pas et compare aux fenêtres calculées hors ligne."""
    pcm = np.frombuffer(base64.b64decode(_field(fixture, "pcm48_s16le_b64")), "<i2")
    expected = _field(fixture, "windows")
    chunk = release.windowing.chunk_frames
    stream = Stream(release.windowing)
    steps = [stream.push(pcm[i : i + chunk]) for i in range(0, len(pcm) - chunk + 1, chunk)]
    live = [(s.start, release.decide(s.pcm)) for s in steps if isinstance(s, Ready)]
    if [start for start, _ in live] != [w["start"] for w in expected]:
        raise ValueError("parité : les fenêtres valides diffèrent de la préparation hors ligne")
    for (start, got), want in zip(live, expected, strict=True):
        if not _same(got, want):
            raise ValueError(f"parité : écart sur la fenêtre {start} (score {got.score})")


def _same(got: Decision, want: Mapping[str, Any]) -> bool:
    if not np.allclose(got.flat, want["flat"], rtol=0, atol=FEATURE_ATOL):
        return False
    if abs(got.score - want["score"]) > DECISION_ATOL:
        return False
    if (got.distance_m is None) != (want["distance_m"] is None):
        return False
    return got.distance_m is None or abs(got.distance_m - want["distance_m"]) <= DECISION_ATOL
