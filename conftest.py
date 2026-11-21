import copy
import hashlib
import json
import uuid
from pathlib import Path

import numpy as np
import pytest

# Identifiants lus dans le contrat partagé : les tests n'ont pas leur propre copie de la liste.
_CONTRACT = Path(__file__).parent / "contracts" / "profiles.json"
TEAM_PROFILES = frozenset(p["id"] for p in json.loads(_CONTRACT.read_text("utf-8"))["profiles"])

BASE_SETTINGS = {
    "capture_contract": "edth.web-pcm.v1",
    "recorder": "audio_worklet_pcm",
    "echoCancellation": False,
    "noiseSuppression": False,
    "autoGainControl": False,
    "sample_rate": 48000,
    "channels": 1,
    "channel_selection": "first",
    "input_channels": 1,
    "sample_format": "pcm_s16le",
    "browser": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari",
    "microphone_label": "Default",
    "track_settings": {"echoCancellation": False, "channelCount": 1},
    "system_processing": "unverified",
}


def make_hello(**overrides):
    settings = copy.deepcopy(BASE_SETTINGS)
    settings.update(overrides.pop("settings", {}))
    hello = {
        "type": "hello",
        "protocol": "crozidrone.audio-stream.v1",
        "session_id": str(uuid.uuid4()),
        "profile": "tristan",
        "capture_settings": settings,
        "captured_at": "2026-11-21T10:00:00.000Z",
        "user_agent": settings["browser"],
    }
    hello.update(overrides)
    return hello


def sine(freq=440.0, seconds=1.0, amplitude=0.5, rate=48000):
    t = np.arange(int(seconds * rate)) / rate
    return np.round(amplitude * 32767 * np.sin(2 * np.pi * freq * t)).astype("<i2")


def packet(seq, samples):
    return int(seq).to_bytes(4, "little") + np.asarray(samples, dtype="<i2").tobytes()


@pytest.fixture
def hello():
    return make_hello()


# ---------------------------------------------------------------- bundle de release de test (②)
# Reproduit ce que l'export du repo ML livre (contrat d'intégration ML v2, release r1) avec la copie
# figée de dsp.py / features.py / ml.py : modèles aux poids aléatoires (pas d'entraînement), lot de
# parité calculé HORS LIGNE sur chaque extrait entier (dsp.iter_windows), comme l'étape 05 du ML.

BUNDLE_RATE = 48000
BUNDLE_WINDOW_MS, BUNDLE_STEP_MS = 100, 20
BUNDLE_RECOMPUTE = {"band_level_group": "band_levels_avg4", "include_rms": False}


def bundle_signal(seconds=6.0, gap_at=150_000, gap_len=2_400, seed=7):
    """PCM48 de test : bruit + sifflement à niveau variable, et une coupure numérique de 50 ms."""
    rng = np.random.default_rng(seed)
    n = int(seconds * 48000)
    t = np.arange(n) / 48000
    level = 0.05 + 0.3 * (1 + np.sin(2 * np.pi * t / seconds)) / 2
    x = level * np.sin(2 * np.pi * 5000 * t) + 0.02 * rng.standard_normal(n)
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype("<i2")
    if gap_len:
        pcm[gap_at : gap_at + gap_len] = 0
    return pcm


def bundle_features(window):
    from dsp import window_features

    return window_features(window, BUNDLE_RATE, window_ms=BUNDLE_WINDOW_MS, **BUNDLE_RECOMPUTE)


def bundle_windows(pcm):
    """Fenêtres valides hors ligne (index, PCM) selon la géométrie du bundle de test."""
    from dsp import iter_windows

    return iter_windows(pcm, BUNDLE_RATE, window_ms=BUNDLE_WINDOW_MS, stride_ms=BUNDLE_STEP_MS)


def _bundle_columns():
    from dsp import BAND_LEVEL_GROUPS

    return list(BAND_LEVEL_GROUPS[BUNDLE_RECOMPUTE["band_level_group"]])


def _test_mlp(task, frame, rng, bias):
    import ml
    from sklearn.preprocessing import StandardScaler

    model = ml.Mlp(task, lr=1e-3, dropout=0.15)
    model.cols = _bundle_columns()
    model.scaler = StandardScaler().fit(frame[model.cols].to_numpy(float))
    model.layers = [
        (rng.normal(0, 0.5, (16, len(model.cols))), rng.normal(0, 0.1, 16)),
        (rng.normal(0, 0.5, (1, 16)), np.array([bias])),
    ]
    return model


def _frozen_sources():
    """Copies figées de l'appli (packages/features) : celles que la release doit embarquer."""
    import dsp
    import features
    import ml

    return {f"frozen/{Path(m.__file__).name}": Path(m.__file__) for m in (dsp, features, ml)}


def bundle_manifest(threshold):
    samples = BUNDLE_RATE * BUNDLE_WINDOW_MS // 1000
    step = BUNDLE_RATE * BUNDLE_STEP_MS // 1000
    columns = _bundle_columns()
    return {
        "contract": "edth.model-release.v2",
        "release": "test.48k-w100.r0",
        "created_utc": "2026-11-21T22:00:00Z",
        "frozen": {
            "repo_commit": "f6c6ce40243abc299a3ab64b81ae9537f24dfa90",
            "files": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for name, path in _frozen_sources().items()},
        },
        "input": {
            "transport": {"rate_hz": 48000, "format": "pcm_s16le", "channels": 1},
            "model_rate_hz": BUNDLE_RATE,
            "fir": None,
            "window": {"ms": BUNDLE_WINDOW_MS, "step_ms": BUNDLE_STEP_MS,
                       "samples": samples, "step_samples": step},
            "qc": {"zero_run_ms": 40, "guard_ms": 500, "start_guard_ms": 500},
        },
        "features": {
            "fft": 2048, "hop": 1024,
            "band_levels": {"count": 50, "source_bands": 200, "average": 4},
            "logfft": None, "local_only": True, "recompute": dict(BUNDLE_RECOMPUTE),
        },
        "detection": {"file": "detection/model.joblib", "model": "mlp", "columns": columns,
                      "threshold": threshold, "rule": "single_window"},
        "distance": {"file": "distance/model.joblib", "model": "mlp", "columns": columns,
                     "bounds_m": [1.0, 5.0]},
    }


EXCERPT_48K = 28_800  # une session du lot de parité r1 : amorce 500 ms + fenêtre 100 ms


def _b64(array):
    import base64

    return base64.b64encode(np.asarray(array).astype("<i2").tobytes()).decode()


def _parity_case(k, excerpt, start, window, feats, score, distance, threshold):
    return {
        "sample_id": f"case-{k}", "device_id": "test", "split": "validation",
        "drone_present": None, "distance_m": None,
        "excerpt": {"pcm48_b64": _b64(excerpt), "samples_48k": len(excerpt),
                    "window_start_offset": int(start), "guard_samples_48k": 24000},
        "expected": {"window_pcm_b64": _b64(window), "window_ms": BUNDLE_WINDOW_MS,
                     "recompute": dict(BUNDLE_RECOMPUTE),
                     "flat": {c: float(feats[c]) for c in _bundle_columns()},
                     "score": float(score), "distance_m": float(distance),
                     "present": bool(score >= threshold)},
    }


def write_model_bundle(root, seed=3, cases=4):
    """Écrit un bundle complet dans root (format de la release r1) ; renvoie (manifeste, lot).
    Lot de parité : `cases` sessions de 600 ms prises dans le signal de test, chacune avec sa
    fenêtre attendue calculée hors ligne. Le seuil vaut la médiane des scores : le lot a des cas
    des deux côtés du seuil."""
    import joblib
    import pandas as pd

    pcm = bundle_signal(gap_len=0)
    frame = pd.DataFrame([bundle_features(w) for _, w in bundle_windows(pcm)])
    rng = np.random.default_rng(seed)
    detection = _test_mlp("classification", frame, rng, bias=0.0)
    distance = _test_mlp("distance", frame, rng, bias=3.0)
    excerpts = [pcm[k * 72_000 : k * 72_000 + EXCERPT_48K] for k in range(cases)]
    windows = [next(bundle_windows(x)) for x in excerpts]
    feats = [bundle_features(w) for _, w in windows]
    scores = detection.predict(pd.DataFrame(feats))
    distances = distance.predict(pd.DataFrame(feats))
    threshold = float(np.median(scores))
    manifest = bundle_manifest(threshold)
    fixture = {
        "contract": manifest["contract"], "release": manifest["release"],
        "model_rate_hz": BUNDLE_RATE, "transport_rate_hz": 48000, "chunk_hint_samples_48k": 2400,
        "replay": "une session = un extrait (amorce 500 ms + fenêtre) ; fenêtre à "
                  "window_start_offset dans le flux au taux modèle",
        "cases": [
            _parity_case(k, x, i, w, f, s, d, threshold)
            for k, (x, (i, w), f, s, d) in enumerate(
                zip(excerpts, windows, feats, scores, distances, strict=True)
            )
        ],
    }
    root = Path(root)
    for sub, model in (("detection", detection), ("distance", distance)):
        (root / sub).mkdir(parents=True, exist_ok=True)
        joblib.dump(model, root / sub / "model.joblib")
    (root / "frozen").mkdir(exist_ok=True)
    for name, path in _frozen_sources().items():
        (root / name).write_bytes(path.read_bytes())
    (root / "parity").mkdir(exist_ok=True)
    (root / "parity" / "fixture.json").write_text(json.dumps(fixture))
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest, fixture


@pytest.fixture(scope="session")
def model_bundle(tmp_path_factory):
    """Bundle valide partagé (lecture seule) : copier avant de le modifier."""
    root = tmp_path_factory.mktemp("release")
    write_model_bundle(root)
    return root
