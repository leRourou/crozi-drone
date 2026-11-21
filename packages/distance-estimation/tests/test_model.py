"""ModelEstimator : un bloc d'un pas par AudioWindow → une estimation, selon le contrat ML V1 §4."""

import logging

import pytest
from dsp import iter_windows

from conftest import BUNDLE_RATE, bundle_signal
from distance_estimation.estimator import AudioWindow, Range
from distance_estimation.model import ModelEstimator
from distance_estimation.release import load_release

UNCERTAINTY = 0.15


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


def test_chunks_are_one_step_of_the_release(release):
    assert ModelEstimator(release, UNCERTAINTY).chunk_frames == 12000


def test_each_chunk_gives_the_offline_decision_of_the_window_it_completes(release, signal):
    estimator = ModelEstimator(release, UNCERTAINTY)
    estimates = replay(estimator, chunks(signal, estimator.chunk_frames))
    expected = {i: release.decide(w).distance_m for i, w in iter_windows(signal, BUNDLE_RATE)}
    step, samples = release.windowing.step, release.windowing.samples
    for k, estimate in enumerate(estimates):
        start = (k + 1) * step - samples
        distance = expected.get(start)
        assert (estimate.profile, estimate.t) == ("noe", float(k))
        if distance is None:
            assert estimate.range is None
        else:
            assert estimate.range == Range(pytest.approx(distance, abs=1e-6), UNCERTAINTY)
    assert any(e.drone for e in estimates) and not all(e.drone for e in estimates)


def test_a_new_session_restarts_from_a_fresh_stream(release, signal):
    estimator = ModelEstimator(release, UNCERTAINTY)
    pcm_chunks = chunks(signal, estimator.chunk_frames)
    first = replay(estimator, pcm_chunks)
    second = replay(estimator, pcm_chunks, session_id="s2")
    assert second == first


def test_phones_have_independent_streams(release, signal):
    estimator = ModelEstimator(release, UNCERTAINTY)
    pcm_chunks = chunks(signal, estimator.chunk_frames)
    alone = replay(ModelEstimator(release, UNCERTAINTY), pcm_chunks, profile="tristan")
    replay(estimator, pcm_chunks[:5], profile="noe")
    assert replay(estimator, pcm_chunks, profile="tristan") == alone


def test_a_chunk_of_the_wrong_size_is_a_programming_error(release):
    estimator = ModelEstimator(release, UNCERTAINTY)
    with pytest.raises(ValueError, match="12000"):
        estimator.estimate(AudioWindow("noe", "s1", 0.0, b"\x00\x00" * 6000))


def test_skipped_windows_are_logged_when_the_reason_changes_only(release, signal, caplog):
    estimator = ModelEstimator(release, UNCERTAINTY)
    with caplog.at_level(logging.INFO, logger="crozidrone.model"):
        replay(estimator, chunks(signal, estimator.chunk_frames))
    reasons = [r.getMessage() for r in caplog.records]
    assert reasons == [
        "event=model_window_skipped profile=noe reason=warmup",
        "event=model_window_skipped profile=noe reason=dropout",
    ]

