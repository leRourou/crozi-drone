"""ModelEstimator : un bloc d'une période par AudioWindow → une estimation (contrat ML v2 §4) sur
la dernière fenêtre de la période ; décimation et contrôle qualité voient tous les échantillons."""

import logging

import pytest

from conftest import bundle_signal, bundle_windows
from distance_estimation.estimator import AudioWindow, Range
from distance_estimation.model import ModelEstimator
from distance_estimation.release import load_release

UNCERTAINTY = 0.15
PERIOD_MS = 100  # 5 pas de 20 ms


@pytest.fixture(scope="module")
def release(model_bundle):
    return load_release(model_bundle)


@pytest.fixture(scope="module")
def signal():
    """Signal avec une coupure numérique : fenêtres valides et exclues, présentes et absentes."""
    return bundle_signal()


def chunks(pcm, chunk_frames):
    last = len(pcm) - chunk_frames + 1
    return [pcm[i : i + chunk_frames].tobytes() for i in range(0, last, chunk_frames)]


def replay(estimator, pcm_chunks, profile="noe", session_id="s1"):
    return [
        estimator.estimate(AudioWindow(profile, session_id, float(k), chunk))
        for k, chunk in enumerate(pcm_chunks)
    ]


def estimator_for(release, period_ms=PERIOD_MS):
    return ModelEstimator(release, UNCERTAINTY, period_ms)


@pytest.mark.parametrize(("period_ms", "frames"), [(20, 960), (100, 4800), (240, 11520)])
def test_a_chunk_is_one_period_a_whole_number_of_steps(release, period_ms, frames):
    assert estimator_for(release, period_ms).chunk_frames == frames


@pytest.mark.parametrize("period_ms", [10, 30, 0])
def test_a_period_that_is_not_a_whole_number_of_steps_is_refused(release, period_ms):
    with pytest.raises(ValueError, match="20 ms"):
        estimator_for(release, period_ms)


@pytest.mark.parametrize("period_ms", [20, 100])
def test_each_chunk_gives_the_offline_decision_of_the_last_window_it_completes(
    release, signal, period_ms
):
    estimator = estimator_for(release, period_ms)
    estimates = replay(estimator, chunks(signal, estimator.chunk_frames))
    expected = {i: release.decide(w).distance_m for i, w in bundle_windows(signal)}
    chunk, samples = estimator.chunk_frames, release.windowing.samples  # 48 kHz : pas de décimation
    for k, estimate in enumerate(estimates):
        start = (k + 1) * chunk - samples
        distance = expected.get(start)
        assert (estimate.profile, estimate.t) == ("noe", float(k))
        if distance is None:
            assert estimate.range is None
        else:
            assert estimate.range == Range(pytest.approx(distance, abs=1e-6), UNCERTAINTY)
    assert any(e.drone for e in estimates) and not all(e.drone for e in estimates)
    assert len(estimates) == len(signal) // chunk


def test_a_new_session_restarts_from_a_fresh_stream(release, signal):
    estimator = estimator_for(release)
    pcm_chunks = chunks(signal, estimator.chunk_frames)
    first = replay(estimator, pcm_chunks)
    second = replay(estimator, pcm_chunks, session_id="s2")
    assert second == first


def test_phones_have_independent_streams(release, signal):
    estimator = estimator_for(release)
    pcm_chunks = chunks(signal, estimator.chunk_frames)
    alone = replay(estimator_for(release), pcm_chunks, profile="tristan")
    replay(estimator, pcm_chunks[:5], profile="noe")
    assert replay(estimator, pcm_chunks, profile="tristan") == alone


def test_a_chunk_of_the_wrong_size_is_a_programming_error(release):
    estimator = estimator_for(release)
    with pytest.raises(ValueError, match="4800"):
        estimator.estimate(AudioWindow("noe", "s1", 0.0, b"\x00\x00" * 960))


def test_skipped_windows_are_logged_when_the_reason_changes_only(release, signal, caplog):
    estimator = estimator_for(release)
    with caplog.at_level(logging.INFO, logger="crozidrone.model"):
        replay(estimator, chunks(signal, estimator.chunk_frames))
    reasons = [r.getMessage() for r in caplog.records]
    assert reasons == [
        "event=model_window_skipped profile=noe reason=warmup",
        "event=model_window_skipped profile=noe reason=dropout",
    ]

