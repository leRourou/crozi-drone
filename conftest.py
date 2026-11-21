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
# Reproduit ce que l'export du repo ML livrera (contrat d'intégration ML V1) avec la copie figée de
# dsp.py / ml.py : modèles aux poids aléatoires (pas d'entraînement), lot de parité calculé HORS
# LIGNE sur le flux entier (dsp.iter_windows), comme la préparation de l'étape 01.

BUNDLE_RATE = 24000


def bundle_signal(seconds=6.0, gap_at=150_000, gap_len=2_400, seed=7):
    """PCM48 de test : bruit + sifflement à niveau variable, et une coupure numérique de 50 ms.
    La coupure se termine avant la fin de fenêtre suivante : pas d'écart causal (voir stream.py)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * 48000)
    t = np.arange(n) / 48000
    level = 0.05 + 0.3 * (1 + np.sin(2 * np.pi * t / seconds)) / 2
    x = level * np.sin(2 * np.pi * 5000 * t) + 0.02 * rng.standard_normal(n)
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype("<i2")
    if gap_len:
        pcm[gap_at : gap_at + gap_len] = 0
    return pcm


def _test_models(frame, rng):
    import ml
    from dsp import FLAT_COLS
    from sklearn.preprocessing import StandardScaler

    cnn = ml.CnnPresence(lr=1e-3, dropout=0.15)
    cnn.state = {
        "0.weight": rng.normal(0, 0.3, (32, 1, 3, 3)).astype(np.float32),
        "0.bias": rng.normal(0, 0.1, 32).astype(np.float32),
        "5.weight": rng.normal(0, 0.3, (1, 128)).astype(np.float32),
        "5.bias": np.zeros(1, dtype=np.float32),
    }
    x = ml.logmel_array(frame) - frame["rms_db"].to_numpy(float)[:, None, None]
    cnn.mu, cnn.sd = x.mean(axis=(0, 2)), np.maximum(x.std(axis=(0, 2)), 1e-6)
    mlp = ml.Mlp("distance", lr=1e-3, dropout=0.15)
    mlp.cols = list(FLAT_COLS)
    mlp.scaler = StandardScaler().fit(frame[FLAT_COLS].to_numpy(float))
    mlp.layers = [
        (rng.normal(0, 0.5, (16, len(FLAT_COLS))), rng.normal(0, 0.1, 16)),
        (rng.normal(0, 0.5, (1, 16)), np.array([3.0])),
    ]
    return cnn, mlp


def _fir_sha(rate):
    from dsp import antialias_fir

    fir = antialias_fir(rate)
    return None if fir is None else hashlib.sha256(fir.astype("<f8").tobytes()).hexdigest()


def _frozen_sources():
    """Copies figées de l'appli (packages/features) : celles que la release doit embarquer."""
    import dsp
    import ml

    return {f"frozen/{Path(m.__file__).name}": Path(m.__file__) for m in (dsp, ml)}


def bundle_manifest(threshold, rate=BUNDLE_RATE):
    from dsp import FLAT_COLS, n_frames

    return {
        "contract": "edth.model-release.v1",
        "release": "test.24k-1s.r0",
        "created_utc": "2026-11-21T20:00:00Z",
        "frozen": {
            "repo_commit": "ec518233128d99f83acac6fa3c9dd8581220f210",
            "files": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for name, path in _frozen_sources().items()},
        },
        "input": {
            "transport": {"rate_hz": 48000, "format": "pcm_s16le", "channels": 1},
            "model_rate_hz": rate,
            "fir": {"taps": 161, "cutoff_hz": 11000, "kaiser_beta": 8.6,
                    "coefficients_sha256": _fir_sha(rate)},
            "window": {"ms": 1000, "step_ms": 250, "samples": rate, "step_samples": rate // 4},
            "qc": {"zero_run_ms": 40, "guard_ms": 500, "start_guard_ms": 500},
        },
        "features": {"fft": 2048, "hop": 1024, "flat_columns": list(FLAT_COLS),
                     "logmel": {"mels": 32, "frames": n_frames(rate), "dtype": "float32"}},
        "detection": {"file": "detection/model.joblib", "model": "cnn",
                      "threshold": threshold, "rule": "single_window"},
        "distance": {"file": "distance/model.joblib", "model": "mlp", "bounds_m": [1.0, 5.0]},
    }


EXCERPT_48K = 72_000  # une session du lot de parité r0 : amorce 500 ms + fenêtre 1 s


def _b64(array):
    import base64

    return base64.b64encode(np.asarray(array).astype("<i2").tobytes()).decode()


def _parity_case(k, excerpt, start, window, features, score, distance, threshold):
    from dsp import FLAT_COLS, LOGMEL

    return {
        "sample_id": f"case-{k}", "device_id": "test", "split": "dev",
        "drone_present": None, "distance_m": None,
        "excerpt": {"pcm48_b64": _b64(excerpt), "samples_48k": len(excerpt),
                    "window_start_offset_24k": int(start), "guard_samples_48k": 24000},
        "expected": {"window_pcm24_b64": _b64(window),
                     "flat": {c: float(features[c]) for c in FLAT_COLS},
                     "logmel": [float(v) for v in features[LOGMEL]],
                     "score": float(score), "distance_m": float(distance),
                     "present": bool(score >= threshold)},
    }


def write_model_bundle(root, seed=3, cases=4):
    """Écrit un bundle complet dans root (format de la release r0) ; renvoie (manifeste, lot).
    Lot de parité : `cases` sessions de 1,5 s découpées dans le signal de test, chacune avec sa
    fenêtre attendue calculée hors ligne (dsp.iter_windows), comme 05_export_release du repo ML.
    Le seuil vaut la médiane des scores : le lot a des cas des deux côtés du seuil."""
    import joblib
    import pandas as pd
    from dsp import iter_windows, window_features

    pcm = bundle_signal(gap_len=0)
    rows = [window_features(w, BUNDLE_RATE) for _, w in iter_windows(pcm, BUNDLE_RATE)]
    frame = pd.DataFrame(rows)
    cnn, mlp = _test_models(frame, np.random.default_rng(seed))
    excerpts = [pcm[k * EXCERPT_48K : (k + 1) * EXCERPT_48K] for k in range(cases)]
    windows = [next(iter_windows(x, BUNDLE_RATE)) for x in excerpts]
    features = [window_features(w, BUNDLE_RATE) for _, w in windows]
    scores = cnn.predict(pd.DataFrame(features))
    distances = mlp.predict(pd.DataFrame(features))
    threshold = float(np.median(scores))
    manifest = bundle_manifest(threshold)
    fixture = {
        "contract": manifest["contract"], "release": manifest["release"],
        "model_rate_hz": BUNDLE_RATE, "transport_rate_hz": 48000, "chunk_hint_samples_48k": 2400,
        "replay": "une session = un extrait (amorce 500 ms + fenêtre 1 s) ; décimation continue "
                  "par blocs, fenêtre à window_start_offset_24k",
        "cases": [
            _parity_case(k, x, i, w, f, s, d, threshold)
            for k, (x, (i, w), f, s, d) in enumerate(
                zip(excerpts, windows, features, scores, distances, strict=True)
            )
        ],
    }
    root = Path(root)
    for sub, model in (("detection", cnn), ("distance", mlp)):
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
