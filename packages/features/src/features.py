"""Spectral features for one band or a collection of pre-split bands.

Pass (frames, bins) for a single band or (bands, frames, bins) for stacked
bands. Channel data adds a final axis. Use split=False for a single
multichannel band, since its three axes overlap with stacked mono input.
The list returned by get_multibands also supports unequal band widths.
"""

import numpy as np
from scipy.signal import lfilter

SPLIT_SIZE = 0.05

def to_mono(data):
    """Average the last channel axis of (frames, bins, channels) feature data."""
    data = np.asarray(data)
    return data.mean(axis=-1) if data.ndim == 3 else data


def get_splits(split_size=SPLIT_SIZE):
    if not 0 < split_size <= 1:
        raise ValueError("split_size must be between 0 and 1")
    return np.arange(split_size, 1, split_size)

def get_multibands(amplitudes, split_size=SPLIT_SIZE, *, band_indices=None, n_bands=None):
    """Split the frequency axis, optionally using the original bin indices."""
    if band_indices is None:
        splits = (amplitudes.shape[1] * get_splits(split_size)).astype(int)
    else:
        boundaries = (n_bands * get_splits(split_size)).astype(int)
        splits = np.searchsorted(band_indices, boundaries)
    return np.split(amplitudes, splits, axis=1)

def normalize(data, axis, power=1.0):
    data = np.asarray(data, dtype=float)
    if not np.isfinite(power) or power <= 0:
        raise ValueError("power must be finite and positive")
    if data.shape[axis] == 0:
        return np.zeros_like(data, dtype=float)

    def norm(values):
        low = np.min(values, axis=axis, keepdims=True)
        span = np.max(values, axis=axis, keepdims=True) - low
        return np.clip(np.divide(
            2 * (values - low) - span,
            span,
            out=np.zeros_like(values),
            where=span != 0,
        ), -1, 1)

    data = norm(data)
    return norm(np.sign(data) * np.abs(data) ** power)


def _as_bands(amplitudes, split):
    if split is None:
        split = isinstance(amplitudes, (list, tuple)) or np.ndim(amplitudes) > 2
    return amplitudes if split else (amplitudes,), split


def _normalize_bands(results, split, power):
    values = np.stack(tuple(results))
    values = normalize(values, axis=1, power=power)
    return values if split else values[0]


def _apply_to_bands(amplitudes, feature, power, split):
    bands, split = _as_bands(amplitudes, split)
    return _normalize_bands((feature(to_mono(band)) for band in bands), split, power)


def get_abs_amp_max(abs_amplitudes, power=1.0, *, split=None):
    return _apply_to_bands(
        abs_amplitudes, lambda band: np.max(band, axis=1, initial=0), power, split
    )


def get_abs_amp_nonzero_count(abs_amplitudes, power=1.0, *, split=None, threshold=None):
    """Count bins per frame, optionally above a scalar or per-frame threshold."""
    def count(band):
        active = band if threshold is None else band > threshold
        return np.count_nonzero(active, axis=1)

    return _apply_to_bands(abs_amplitudes, count, power, split)


def get_abs_amp_avg_frequency(abs_amplitudes, frequencies, power=1.0, *, split=None):
    return get_mb_s_centroid(abs_amplitudes, frequencies, power, split=split)


def get_abs_amp_std(abs_amplitudes, power=1.0, *, split=None):
    def std(band):
        return np.std(band, axis=1) if band.shape[1] else np.zeros(band.shape[0])

    return _apply_to_bands(abs_amplitudes, std, power, split)


def get_mb_entropy(amplitudes, power=1.0, *, split=None):
    def entropy(band):
        total = band.sum(axis=1, keepdims=True)
        p = np.divide(band, total, out=np.zeros_like(band, dtype=float), where=total != 0)
        logp = np.log2(p, out=np.zeros_like(p), where=p > 0)
        return -(p * logp).sum(axis=1)

    return _apply_to_bands(amplitudes, entropy, power, split)


def get_mb_onset(amplitudes, power=1.0, *, split=None):
    """Calculate positive flux after subtracting the noise floor."""
    def onset(band):
        flux = _spectral_flux(band)
        if not flux.size:
            return flux
        floor = lfilter([0.05], [1, -0.95], flux)
        return np.maximum(flux - floor, 0)

    return _apply_to_bands(amplitudes, onset, power, split)


def get_mb_s_centroid(amplitudes, frequencies=None, power=1.0, *, split=None):
    """Use a flat frequency vector, one vector per band, or global bin indices."""
    bands, split = _as_bands(amplitudes, split)
    bands = [to_mono(band) for band in bands]
    widths = [band.shape[1] for band in bands]
    if frequencies is None:
        frequencies = np.arange(sum(widths))
    if not len(frequencies) or np.isscalar(frequencies[0]):
        frequencies = np.split(frequencies, np.cumsum(widths)[:-1])
    if len(frequencies) != len(bands) or any(
        np.shape(freq) != (width,) for freq, width in zip(frequencies, widths)
    ):
        raise ValueError("Frequencies must match the bins in each band")

    def centroid(band, freq):
        total = band.sum(axis=1)
        return np.divide(
            (band * freq).sum(axis=1), total,
            out=np.zeros_like(total, dtype=float), where=total != 0,
        )

    return _normalize_bands(
        (centroid(band, freq) for band, freq in zip(bands, frequencies)), split, power
    )


def get_mb_s_flux(amplitudes, power=1.0, *, split=None):
    """Positive frame-to-frame spectral change, normalized per band over time."""
    return _apply_to_bands(amplitudes, _spectral_flux, power, split)


def _spectral_flux(band):
    """Mean positive change from the previous frame; first frame starts from silence."""
    changes = np.diff(np.asarray(band, dtype=float), axis=0, prepend=0)
    return np.maximum(changes, 0).sum(axis=1) / max(band.shape[1], 1)


def get_mb_zcr(amplitudes, power=1.0, *, split=None):
    """Row sign-change rate. Magnitude spectra give zero; waveform ZCR needs signed samples."""
    def zcr(band):
        changes = np.diff(np.signbit(band), axis=1)
        return np.count_nonzero(changes, axis=1) / max(band.shape[1] - 1, 1)

    return _apply_to_bands(amplitudes, zcr, power, split)


def get_mb_crest_factor(amplitudes, power=1.0, *, split=None):
    """Peak/RMS of combined channel magnitudes across axis 1; silence gives zero."""
    def crest_factor(band):
        band = np.asarray(band, dtype=float)
        rms = np.sqrt((band ** 2).sum(axis=1) / max(band.shape[1], 1))
        peak = np.max(np.abs(band), axis=1, initial=0)
        return np.divide(peak, rms, out=np.zeros_like(rms), where=rms != 0)

    return _apply_to_bands(amplitudes, crest_factor, power, split)

HANDCRAFTED_COLS = ["entropy", "zcr", "crest_factor", "centroid", "flux", "onset"]
BAND_DESCRIPTOR_NAMES = ("entropy", "centroid", "flux", "onset")


def band_descriptor_features(amplitudes, frequencies, boundaries):
    """Compute four descriptors per frequency band for one recording."""
    bands = np.split(amplitudes, boundaries, axis=1)
    scores = {
        "entropy": get_mb_entropy(bands),
        "centroid": get_mb_s_centroid(bands, frequencies),
        "flux": get_mb_s_flux(bands),
        "onset": get_mb_onset(bands),
    }
    return {f"{name}_band_{index}": values
            for name, results in scores.items()
            for index, values in enumerate(results)}


def handcrafted_features(waveforms, amplitudes, frequencies):
    """Compute whole-window features in time order for one recording."""
    return {
        "entropy": get_mb_entropy(amplitudes),
        "zcr": get_mb_zcr(waveforms),
        "crest_factor": get_mb_crest_factor(waveforms),
        "centroid": get_mb_s_centroid(amplitudes, frequencies),
        "flux": get_mb_s_flux(amplitudes),
        "onset": get_mb_onset(amplitudes),
    }
