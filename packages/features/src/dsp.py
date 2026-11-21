"""Chaîne audio 48 kHz -> taux cible et features d'une fenêtre d'une seconde.

Taux : 16000, 24000 (référence historique, parité exacte avec les modèles
entraînés) ou 48000 (aucun filtrage). Coupures numériques >= 40 ms masquées,
garde 500 ms, fenêtres de 1 s toutes les 250 ms, niveaux absolus en dBFS.
"""
import wave
from functools import lru_cache

import numpy as np

MASTER = 48000
RATES = (16000, 24000, 48000)
DROPOUT = 1920   # 40 ms de zéros exacts à 48 kHz
GUARD = 24000    # 500 ms de garde à 48 kHz
N_BANDS, FFT, HOP = 32, 2048, 1024
BAND_COLS = [f"f{i}" for i in range(N_BANDS)]
FLAT_COLS = BAND_COLS + ["b4_8", "rms_db"]
LOGMEL = "logmel"
FEATURE_SETS = {"mel": BAND_COLS, "b48": ["b4_8"], "rms": ["rms_db"]}


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


def iter_windows(pcm48, rate):
    """Fenêtres valides (index de départ, 1 s au taux cible) d'un flux contigu 48 kHz."""
    x = pcm16(pcm48)
    fir = antialias_fir(rate)
    factor = MASTER // rate
    y = x if fir is None else Decimator(rate).process(x)
    if len(y) < rate:
        return
    zero = x == 0
    changes = np.flatnonzero(np.diff(zero, prepend=False, append=False)).reshape(-1, 2)
    gaps = changes[changes[:, 1] - changes[:, 0] >= DROPOUT]
    for i in range(rate // 2, len(y) - rate + 1, rate // 4):
        if np.any((gaps[:, 0] < factor * (i + rate)) & (gaps[:, 1] + GUARD > factor * i)):
            continue
        yield i, y[i:i + rate]


@lru_cache(maxsize=None)
def _layout(rate):
    nyq = rate // 2
    freq = np.fft.rfftfreq(FFT, 1 / rate)
    edges = 700 * np.expm1(np.linspace(0, np.log1p(nyq / 700), N_BANDS + 1))
    edges[[0, -1]] = [0, nyq]
    mel = 700 * np.expm1(np.linspace(0, np.log1p(nyq / 700), N_BANDS + 2))
    mel[[0, -1]] = [0, nyq]
    filters = np.clip(np.minimum(
        (freq[None, :] - mel[:-2, None]) / np.maximum(mel[1:-1, None] - mel[:-2, None], 1e-12),
        (mel[2:, None] - freq[None, :]) / np.maximum(mel[2:, None] - mel[1:-1, None], 1e-12)), 0, None)
    filters.setflags(write=False)
    hann = np.hanning(FFT + 1)[:-1]
    hann.setflags(write=False)
    return np.searchsorted(freq, edges[:-1]), filters, freq, hann


def n_frames(rate):
    return (rate - FFT) // HOP + 1


def resolve_features(spec):
    """"mel,b48,rms" -> colonnes plates dans un ordre fixe ; vide = tout."""
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    unknown = [t for t in tokens if t not in FEATURE_SETS]
    if unknown:
        raise ValueError(f"groupes inconnus : {unknown} (choisir parmi {list(FEATURE_SETS)})")
    if not tokens:
        return list(FLAT_COLS)
    return [c for name in ("mel", "b48", "rms") if name in tokens for c in FEATURE_SETS[name]]


def window_features(pcm, rate):
    """Toutes les features d'une fenêtre valide d'une seconde au taux cible."""
    x = pcm16(pcm).astype("float64") / 32768
    if len(x) != rate:
        raise ValueError(f"attendu 1 s ({rate} échantillons), reçu {len(x)}")
    bins, filters, freq, hann = _layout(rate)
    frames = np.lib.stride_tricks.sliding_window_view(x, FFT)[::HOP]
    if len(frames) != n_frames(rate):
        raise ValueError(f"attendu {n_frames(rate)} trames, reçu {len(frames)}")
    spectrum = abs(np.fft.rfft(frames * hann, axis=1)) ** 2
    p = spectrum.mean(axis=0) / ((hann @ hann) * FFT)
    p[1:-1] *= 2
    per_frame = spectrum / ((hann @ hann) * FFT)
    per_frame[:, 1:-1] *= 2
    db = lambda v: 10 * np.log10(np.maximum(v, 1e-12))
    out = dict(zip(BAND_COLS, db(np.add.reduceat(p, bins)).tolist()))
    out["b4_8"] = float(db(p[(freq >= 4000) & (freq < 8000)].sum()))
    out["rms_db"] = float(db(np.mean(x * x)))
    out[LOGMEL] = db(per_frame @ filters.T).T.reshape(-1).astype(np.float32)
    return out
