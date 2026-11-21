"""Chaîne audio 48 kHz -> taux cible et features de fenêtres configurables.

Taux de 16000, 24000 (filtre historique) ou 48000 Hz (aucun filtrage).
Coupures numériques >= 40 ms masquées, garde 500 ms, niveaux absolus en dBFS.
"""
import wave
from functools import lru_cache

import numpy as np
from features import (BAND_DESCRIPTOR_NAMES, HANDCRAFTED_COLS, band_descriptor_features,
                      handcrafted_features)

MASTER = 48000
RATES = (16000, 24000, 48000)
WINDOW_MS, STRIDE_MS = 100, 20
DEFAULT_CACHE_TAG = f"w{WINDOW_MS}-s{STRIDE_MS}"
DROPOUT = 1920   # 40 ms de zéros exacts à 48 kHz
GUARD = 24000    # 500 ms de garde à 48 kHz
FFT, HOP = 2048, 1024
N_BINS = FFT // 2 + 1
FFT_COLS = [f"fft_{i}" for i in range(N_BINS)]
BAND_LEVEL_LAYOUTS = {
    "band_levels": (100, 1),
    "band_levels_avg3": (200, 3),
    "band_levels_avg4": (200, 4),
    "band_levels_avg5": (200, 5),
    "band_levels_avg6": (300, 6),
}
BAND_LEVEL_GROUPS = {
    name: [f"band_level_{i}" if average == 1 else f"band_level_avg{average}_{i}"
           for i in range((count + average - 1) // average)]
    for name, (count, average) in BAND_LEVEL_LAYOUTS.items()
}
BAND_LEVEL_COLS = BAND_LEVEL_GROUPS["band_levels"]
DEFAULT_BAND_GROUP = "band_levels_avg4"
BAND_DESCRIPTOR_GROUP = "band_descriptors_avg4"
LOGFFT = "logfft"
FLAT_COLS = [*FFT_COLS, "rms_db", *HANDCRAFTED_COLS]
FEATURE_SETS = {"fft": FFT_COLS, "rms": ["rms_db"], "handcrafted": HANDCRAFTED_COLS,
                "b48": ["b4_8"], **BAND_LEVEL_GROUPS,
                BAND_DESCRIPTOR_GROUP: [f"{name}_band_{i}" for name in BAND_DESCRIPTOR_NAMES
                                        for i in range(len(BAND_LEVEL_GROUPS[DEFAULT_BAND_GROUP]))]}
DEFAULT_FEATURES = DEFAULT_BAND_GROUP


def default_window_cache(directory, *, full_spectrum=False):
    suffix = "" if full_spectrum else "-bands200-avg4"
    preferred = directory / f"windows-{MASTER}{suffix}-{DEFAULT_CACHE_TAG}.parquet"
    if full_spectrum and not preferred.is_file():
        for rate in (24000, 16000, 48000):
            candidate = directory / f"windows-{rate}.parquet"
            if candidate.is_file():
                return candidate
    return preferred


def pcm16(a):
    a = np.asarray(a)
    if a.ndim != 1 or a.dtype.kind != "i" or a.dtype.itemsize != 2:
        raise ValueError("attendu un tableau mono PCM16 signé")
    return a


def antialias_fir(rate):
    """FIR passe-bas Kaiser ; None si rien à filtrer. 24 kHz = conception historique."""
    if rate == MASTER:
        return None
    if rate not in RATES:
        raise ValueError(f"taux supportés : {RATES}")
    cutoff, taps = (11000, 161) if rate == 24000 else (7333, 241)
    fir = np.sinc(2 * cutoff / MASTER * (np.arange(taps) - taps // 2)) * np.kaiser(taps, 8.6)
    fir /= fir.sum()
    return fir


class Decimator:
    """48 kHz PCM16 -> taux cible, état conservé entre blocs (une instance par flux)."""

    def __init__(self, rate):
        self.rate, self.fir = rate, antialias_fir(rate)
        self.ratio = MASTER // rate
        self.history = np.zeros(0 if self.fir is None else len(self.fir) - 1, dtype=np.int16)
        self.phase = 0

    def process(self, pcm):
        x = pcm16(pcm)
        if self.fir is None or not x.size:
            return x if self.fir is None else np.empty(0, dtype=np.int16)
        padded = np.concatenate((self.history, x))
        filtered = np.convolve(padded, self.fir, "valid")[self.phase::self.ratio]
        self.history = padded[-(len(self.fir) - 1):].copy()
        # le prochain bloc doit reprendre la grille globale : j ≡ -S (mod ratio)
        self.phase = (self.phase - len(x)) % self.ratio
        return np.clip(np.rint(filtered), -32768, 32767).astype(np.int16)


def read_wav48(path):
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getcomptype()) != (48000, 1, 2, "NONE"):
            raise ValueError(f"pas un WAV mono PCM16 48 kHz : {path}")
        n = w.getnframes()
        raw = w.readframes(n)
    if len(raw) != 2 * n:
        raise ValueError(f"WAV tronqué : {path}")
    return np.frombuffer(raw, "<i2")


def window_samples(rate, window_ms=WINDOW_MS):
    samples = rate * window_ms // 1000
    if samples < FFT:
        raise ValueError(f"la fenêtre doit contenir au moins {FFT} échantillons à {rate} Hz")
    return samples


def stride_samples(rate, stride_ms=STRIDE_MS):
    exact_samples = (rate / 1000) * stride_ms
    if not np.isfinite(exact_samples):
        raise ValueError("le pas doit être fini")
    samples = round(exact_samples)
    if samples < 1:
        raise ValueError("le pas doit couvrir au moins un échantillon")
    return samples


def iter_windows(pcm48, rate, *, window_ms=WINDOW_MS, stride_ms=STRIDE_MS):
    """Fenêtres valides (index de départ, PCM au taux cible) d'un flux contigu 48 kHz."""
    width = window_samples(rate, window_ms)
    stride = stride_samples(rate, stride_ms)
    x = pcm16(pcm48)
    fir = antialias_fir(rate)
    factor = MASTER // rate
    y = x if fir is None else Decimator(rate).process(x)
    if len(y) < width:
        return
    zero = x == 0
    changes = np.flatnonzero(np.diff(zero, prepend=False, append=False)).reshape(-1, 2)
    gaps = changes[changes[:, 1] - changes[:, 0] >= DROPOUT]
    for i in range(rate // 2, len(y) - width + 1, stride):
        if np.any((gaps[:, 0] < factor * (i + width)) & (gaps[:, 1] + GUARD > factor * i)):
            continue
        yield i, y[i:i + width]


@lru_cache(maxsize=None)
def _layout(rate):
    freq = np.fft.rfftfreq(FFT, 1 / rate)
    freq.setflags(write=False)
    hann = np.hanning(FFT + 1)[:-1]
    hann.setflags(write=False)
    return freq, hann


def n_frames(rate, window_ms=WINDOW_MS):
    return (window_samples(rate, window_ms) - FFT) // HOP + 1


def resolve_features(spec):
    """Sélectionne les groupes de features dans un ordre fixe."""
    tokens = [t.strip() for t in spec.split(",") if t.strip()] or DEFAULT_FEATURES.split(",")
    unknown = [t for t in tokens if t not in FEATURE_SETS]
    if unknown:
        raise ValueError(f"groupes inconnus : {unknown} (choisir parmi {list(FEATURE_SETS)})")
    return [c for name, columns in FEATURE_SETS.items() if name in tokens for c in columns]


@lru_cache(maxsize=None)
def _band_starts(rate, count):
    lower_edges = np.linspace(0, rate / 2, count, endpoint=False)
    return np.searchsorted(_layout(rate)[0], lower_edges)


def _window_analysis(pcm, rate, window_ms, include_b48, band_level_group=None, include_descriptors=False):
    width = window_samples(rate, window_ms)
    x = pcm16(pcm).astype("float64") / 32768
    if len(x) != width:
        raise ValueError(f"attendu {window_ms} ms ({width} échantillons), reçu {len(x)}")
    freq, hann = _layout(rate)
    frames = np.lib.stride_tricks.sliding_window_view(x, FFT)[::HOP]
    spectrum = abs(np.fft.rfft(frames * hann, axis=1)) ** 2
    p = spectrum.mean(axis=0) / ((hann @ hann) * FFT)
    p[1:-1] *= 2
    db = lambda v: 10 * np.log10(np.maximum(v, 1e-12))
    out = {}
    if band_level_group:
        count, average = BAND_LEVEL_LAYOUTS[band_level_group]
        levels = db(np.add.reduceat(p, _band_starts(rate, count)))
        starts = np.arange(0, count, average)
        pooled = np.add.reduceat(levels, starts) / np.minimum(average, count - starts)
        out.update(zip(FEATURE_SETS[band_level_group], pooled.tolist()))
        if include_descriptors:
            out["rms_db"] = float(db(np.mean(x * x)))
        return out, p
    per_frame = spectrum / ((hann @ hann) * FFT)
    per_frame[:, 1:-1] *= 2
    out.update(zip(FFT_COLS, db(p).tolist()))
    out["rms_db"] = float(db(np.mean(x * x)))
    out[LOGFFT] = db(per_frame).T.reshape(-1).astype(np.float32)
    if include_b48:
        out["b4_8"] = float(db(p[(freq >= 4000) & (freq < 8000)].sum()))
    return out, p


def window_features(pcm, rate, *, window_ms=WINDOW_MS, include_b48=False,
                     band_level_group=None, include_rms=False):
    """Features locales d'une fenêtre valide, sans les autres fenêtres de la prise.

    Les descripteurs normalisés par prise (handcrafted, band_descriptors) ne
    sont PAS calculables ici : ils dépendent des autres fenêtres de la prise.
    """
    return _window_analysis(pcm, rate, window_ms, include_b48, band_level_group, include_rms)[0]


def recording_features(windows, rate, *, window_ms=WINDOW_MS, include_b48=False,
                       band_level_group=None, include_descriptors=False, include_band_descriptors=False):
    """Features des fenêtres d'une prise dans leur ordre temporel."""
    if band_level_group and not (include_descriptors or include_band_descriptors):
        return [dict(start_sample=start, **_window_analysis(pcm, rate, window_ms, False, band_level_group)[0])
                for start, pcm in windows]
    analyses = [(start, pcm, *_window_analysis(pcm, rate, window_ms, include_b48,
                                               band_level_group, include_descriptors))
                for start, pcm in windows]
    if not analyses:
        return []
    starts, waveforms, rows, powers = zip(*analyses)
    amplitudes = np.sqrt(np.stack(powers))
    frequencies = _layout(rate)[0]
    if include_band_descriptors:
        count, average = BAND_LEVEL_LAYOUTS[band_level_group]
        boundaries = _band_starts(rate, count)[average::average]
        scores = band_descriptor_features(amplitudes, frequencies, boundaries)
    else:
        scores = handcrafted_features(np.stack(waveforms), amplitudes, frequencies)
    for index, (start, row) in enumerate(zip(starts, rows)):
        row["start_sample"] = start
        row.update({name: values[index] for name, values in scores.items()})
    return list(rows)
