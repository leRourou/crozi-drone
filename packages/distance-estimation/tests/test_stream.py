"""Chemin live : un flux 48 kHz reçu par blocs d'un pas redonne les fenêtres de la préparation
hors ligne (dsp.iter_windows sur le flux entier), à l'identique."""

import numpy as np
import pytest
from dsp import iter_windows

from conftest import bundle_signal, bundle_windows
from distance_estimation.stream import Ready, Skipped, Stream, Windowing

WINDOWING = Windowing(rate=24000, samples=24000, step=6000, start=12000, zero_run=1920, guard=24000)
CHUNK = WINDOWING.chunk_frames


def live(pcm, windowing=WINDOWING, chunk=CHUNK):
    stream = Stream(windowing)
    return [stream.push(pcm[i : i + chunk]) for i in range(0, len(pcm) - chunk + 1, chunk)]


def ready(steps):
    return [(s.start, s.pcm) for s in steps if isinstance(s, Ready)]


def offline(pcm):
    """Oracle hors ligne dans la géométrie de WINDOWING (24 kHz, 1 s, pas de 250 ms : chemin décimé,
    blocs plus longs qu'une coupure minimale)."""
    return list(iter_windows(pcm, 24000, window_ms=1000, stride_ms=250))


def assert_same_windows(live_windows, offline_windows):
    assert [i for i, _ in live_windows] == [i for i, _ in offline_windows]
    for (_, a), (_, b) in zip(live_windows, offline_windows, strict=True):
        assert np.array_equal(a, b)


def test_a_chunk_is_one_step_of_48_khz_samples():
    assert CHUNK == 12000


def test_no_window_before_the_start_guard_and_a_full_window():
    steps = live(bundle_signal(seconds=1.5, gap_len=0))
    # 1re fenêtre : [0,5 s ; 1,5 s[ au taux modèle, complétée par le 6e bloc de 250 ms
    assert steps[:5] == [Skipped("warmup")] * 5
    assert isinstance(steps[5], Ready) and steps[5].start == 12000


def test_live_windows_are_the_offline_windows_bit_for_bit():
    pcm = bundle_signal(gap_len=0)
    assert_same_windows(ready(live(pcm)), offline(pcm))


def test_a_digital_dropout_invalidates_the_same_windows_as_offline():
    pcm = bundle_signal()
    steps = live(pcm)
    assert Skipped("dropout") in steps
    assert_same_windows(ready(steps), offline(pcm))


def test_a_dropout_straddling_two_chunks_is_seen_as_one_run():
    """1 000 + 1 000 zéros : aucune moitié n'atteint 40 ms, la suite entière si. Hormis la fenêtre
    qui finit au milieu (écart causal, test suivant), live et hors ligne excluent les mêmes."""
    pcm = bundle_signal(gap_at=8 * CHUNK - 1000, gap_len=2000)
    live_starts = [i for i, _ in ready(live(pcm))]
    offline_starts = [i for i, _ in offline(pcm)]
    assert sorted(set(offline_starts) | {8 * WINDOWING.step - WINDOWING.samples}) == live_starts


def test_a_long_dropout_still_running_invalidates_the_window_at_once():
    pcm = bundle_signal(gap_at=8 * CHUNK - 3000, gap_len=3000)  # 62 ms, en cours en fin de bloc
    assert live(pcm)[7] == Skipped("dropout")


def test_a_short_zero_run_still_running_at_window_end_is_not_yet_a_dropout():
    """Écart causal documenté : hors ligne, la suite est vue entière (≥ 40 ms) et la fenêtre est
    exclue ; en live, elle ne mesure que 20 ms à la fin de la fenêtre, qui est donc analysée."""
    pcm = bundle_signal(gap_at=8 * CHUNK - 960, gap_len=2400)
    live_starts = [i for i, _ in ready(live(pcm))]
    offline_starts = [i for i, _ in offline(pcm)]
    assert set(offline_starts) - set(live_starts) == set()
    assert set(live_starts) - set(offline_starts) == {8 * WINDOWING.step - WINDOWING.samples}


def clean_signal(gaps, seconds=6.0):
    """Sifflement décalé, jamais nul : les seuls zéros sont les coupures (début, longueur)."""
    t = np.arange(int(seconds * 48000)) / 48000
    pcm = np.round(1000 + 500 * np.sin(2 * np.pi * 440 * t)).astype("<i2")
    for at, length in gaps:
        pcm[at : at + length] = 0
    return pcm


B = 9 * CHUNK  # une frontière de bloc = une fin de fenêtre (108 000 à 48 kHz)


@pytest.mark.parametrize(
    "gaps",
    [
        pytest.param([(B - 8000, 1920)], id="exactly-zero-run-is-a-dropout"),
        pytest.param([(B - 8000, 1919)], id="one-sample-short-is-not"),
        pytest.param([(B - 1920, 1920)], id="open-at-window-end-exactly-zero-run"),
        pytest.param([(B - CHUNK - 2000, 2000)], id="guard-ends-exactly-at-a-window-start"),
        pytest.param([(B - 2000, 3000)], id="gap-end-counts-not-its-start"),
        pytest.param([(B - 11000, 100), (B - 8000, 2000), (B - 1000, 1500)],
                     id="completed-gap-before-an-open-run"),
        pytest.param([(B - 11000, 100), (B - 2000, 2600)], id="open-run-is-the-last-of-the-chunk"),
    ],
)
def test_dropout_boundaries_match_offline(gaps):
    pcm = clean_signal(gaps)
    assert_same_windows(ready(live(pcm)), offline(pcm))


# ---------------------------------------------------------------- géométrie de la release r1
R1 = Windowing(rate=48000, samples=4800, step=960, start=24000, zero_run=1920, guard=24000)


def test_r1_live_windows_are_the_offline_windows_at_48_khz_without_decimation():
    pcm = bundle_signal(gap_len=0)
    assert_same_windows(ready(live(pcm, R1, R1.chunk_frames)), list(bundle_windows(pcm)))


def test_r1_a_dropout_costs_at_most_two_extra_windows_live():
    """Pas (20 ms) plus court qu'une coupure minimale (40 ms) : les fenêtres qui finissent dans les
    40 premières ms d'une coupure sont encore analysées en live (écart causal), pas hors ligne."""
    pcm = bundle_signal()
    live_starts = {i for i, _ in ready(live(pcm, R1, R1.chunk_frames))}
    offline_starts = {i for i, _ in bundle_windows(pcm)}
    assert offline_starts < live_starts
    assert len(live_starts - offline_starts) <= 2
