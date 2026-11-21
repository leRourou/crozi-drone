import math

import numpy as np
import pytest
from conftest import sine

from app.stats import GAP_THRESHOLD_S, LiveStats, dbfs


def test_dbfs_of_full_scale_and_silence():
    assert dbfs(32768) == pytest.approx(0.0)
    assert dbfs(16384) == pytest.approx(-6.0206, abs=1e-3)
    assert dbfs(0) is None
    assert dbfs(1) == pytest.approx(-90.309, abs=1e-3)


def feed(stats, samples, start, packet_frames=2400, rate=48000, speed=1.0):
    """Simule l'arrivée de paquets au rythme réel (speed=1) et renvoie l'instant final."""
    t = start
    for offset in range(0, len(samples), packet_frames):
        chunk = samples[offset : offset + packet_frames]
        t += len(chunk) / rate / speed
        stats.add(chunk.tobytes(), t)
    return t


def test_realtime_feed_gives_ratio_one_and_768_kbps():
    stats = LiveStats(started_at=100.0)
    end = feed(stats, sine(seconds=1.0), start=100.0)
    snap = stats.snapshot(end)
    assert snap.packets == 20
    assert snap.window_s == pytest.approx(1.0)
    assert snap.packets_per_s == pytest.approx(20.0)
    assert snap.audio_s == pytest.approx(1.0)
    assert snap.rt_ratio == pytest.approx(1.0)
    assert snap.kbps == pytest.approx(768.0)
    assert snap.max_gap_ms == pytest.approx(50.0)
    assert snap.gaps == 0


def test_sine_peak_and_rms_in_dbfs():
    stats = LiveStats(started_at=0.0)
    end = feed(stats, sine(amplitude=0.5, seconds=1.0), start=0.0)
    snap = stats.snapshot(end)
    assert snap.peak_dbfs == pytest.approx(20 * math.log10(0.5 * 32767 / 32768), abs=0.01)
    assert snap.rms_dbfs == pytest.approx(20 * math.log10(0.5 / math.sqrt(2)), abs=0.05)


def test_half_speed_feed_and_gap_are_reported():
    stats = LiveStats(started_at=0.0)
    end = feed(stats, sine(seconds=0.5), start=0.0, speed=0.5)
    stats.add(np.zeros(2400, dtype="<i2").tobytes(), end + 0.4)
    snap = stats.snapshot(end + 0.4)
    assert snap.rt_ratio == pytest.approx(0.55 / 1.4)
    assert snap.gaps == 1
    assert snap.max_gap_ms == pytest.approx(400.0)


def test_window_resets_but_totals_accumulate():
    stats = LiveStats(started_at=0.0)
    t = feed(stats, sine(seconds=1.0), start=0.0)
    stats.snapshot(t)
    empty = stats.snapshot(t + 1.0)
    assert empty.packets == 0
    assert empty.kbps == 0
    assert empty.peak_dbfs is None and empty.rms_dbfs is None
    assert empty.audio_s == pytest.approx(1.0)
    assert empty.rt_ratio == pytest.approx(0.5)


def test_first_packet_interval_counts_from_session_start():
    stats = LiveStats(started_at=10.0)
    stats.add(np.zeros(2400, dtype="<i2").tobytes(), 10.3)
    assert stats.snapshot(10.3).max_gap_ms == pytest.approx(300.0)


def test_interval_equal_to_threshold_is_not_a_gap():
    stats = LiveStats(started_at=0.0)
    stats.add(np.zeros(2, dtype="<i2").tobytes(), GAP_THRESHOLD_S)
    assert stats.snapshot(1.0).gaps == 0


def test_packets_per_s_of_an_empty_window_is_zero():
    stats = LiveStats(started_at=5.0)
    assert stats.snapshot(5.0).packets_per_s == 0.0


def test_packets_per_s_scales_with_window_length():
    stats = LiveStats(started_at=0.0)
    end = feed(stats, sine(seconds=0.5), start=0.0)
    assert stats.snapshot(end).packets_per_s == pytest.approx(20.0)
