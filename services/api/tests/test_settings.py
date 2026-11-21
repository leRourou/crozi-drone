"""Réglages lus dans l'environnement au démarrage ; une valeur invalide empêche de démarrer."""

import pytest

from api.settings import Settings, load_settings


def test_defaults_without_environment():
    assert load_settings({}) == Settings(
        estimator="none",
        window_ms=250,
        state_period_ms=250,
        stale_after_ms=1000,
        detection_fresh_ms=2000,
    )


def test_every_value_comes_from_its_variable():
    env = {
        "DISTANCE_ESTIMATOR": "scripted",
        "DISTANCE_WINDOW_MS": "500",
        "STATE_PERIOD_MS": "100",
        "STALE_AFTER_MS": "1500",
        "DETECTION_FRESH_MS": "3000",
    }
    assert load_settings(env) == Settings("scripted", 500, 100, 1500, 3000)


def test_seconds_are_derived_from_milliseconds():
    s = Settings(window_ms=250, state_period_ms=100, stale_after_ms=1500, detection_fresh_ms=3000)
    assert (s.state_period_s, s.stale_after_s, s.detection_fresh_s) == (0.1, 1.5, 3.0)


def test_window_frames_at_48_khz():
    assert Settings(window_ms=250).window_frames == 12_000


@pytest.mark.parametrize(
    ("env", "variable"),
    [
        ({"DISTANCE_ESTIMATOR": "model"}, "DISTANCE_ESTIMATOR"),
        ({"DISTANCE_WINDOW_MS": "0"}, "DISTANCE_WINDOW_MS"),
        ({"STATE_PERIOD_MS": "-5"}, "STATE_PERIOD_MS"),
        ({"STALE_AFTER_MS": "1.5"}, "STALE_AFTER_MS"),
        ({"DETECTION_FRESH_MS": "abc"}, "DETECTION_FRESH_MS"),
        ({"DETECTION_FRESH_MS": ""}, "DETECTION_FRESH_MS"),
    ],
)
def test_an_invalid_value_refuses_to_start_and_names_the_variable(env, variable):
    with pytest.raises(ValueError, match=variable):
        load_settings(env)


def test_an_invalid_value_is_refused_even_without_the_environment():
    with pytest.raises(ValueError, match="DISTANCE_WINDOW_MS"):
        Settings(window_ms=0)
    with pytest.raises(ValueError, match="DISTANCE_ESTIMATOR"):
        Settings(estimator="model")


def test_one_millisecond_is_the_smallest_accepted_value():
    assert Settings(window_ms=1, state_period_ms=1).state_period_ms == 1
