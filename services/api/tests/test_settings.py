"""Réglages lus dans l'environnement au démarrage ; une valeur invalide empêche de démarrer."""

import pytest

from api.settings import Settings, load_settings

SHA = "811bafcd6fa0e94b287b37133d8d6331b50eb3e3"


def test_defaults_without_environment():
    assert load_settings({}) == Settings(
        estimator="none",
        window_ms=250,
        state_period_ms=250,
        stale_after_ms=1000,
        detection_fresh_ms=2000,
        fusion_spread_ms=500,
        track_accel_std=1.0,
        track_timeout_ms=1000,
        track_altitude_m=1.5,
        track_altitude_std_m=0.5,
        scripted_offset_east_m=0.5,
        scripted_offset_north_m=3.0,
        scripted_radius_m=3.0,
        scripted_altitude_m=1.5,
        scripted_period_s=20.0,
        scripted_range_m=5.0,
        scripted_uncertainty=0.10,
        scripted_noise=0.0,
        model_dir=None,
        model_repo=None,
        model_revision=None,
        model_uncertainty=0.10,
        hf_token=None,
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


def test_the_scripted_drone_and_fusion_values_come_from_their_variables():
    env = {
        "FUSION_SPREAD_MS": "300",
        "SCRIPTED_OFFSET_EAST_M": "-1.25",
        "SCRIPTED_OFFSET_NORTH_M": "0",
        "SCRIPTED_RADIUS_M": "2",
        "SCRIPTED_ALTITUDE_M": "0",
        "SCRIPTED_PERIOD_S": "40",
        "SCRIPTED_RANGE_M": "8.5",
        "SCRIPTED_UNCERTAINTY": "0.2",
        "SCRIPTED_NOISE": "0.05",
    }
    s = load_settings(env)
    assert s.fusion_spread_s == 0.3
    assert (s.scripted_offset_east_m, s.scripted_offset_north_m) == (-1.25, 0.0)
    assert (s.scripted_radius_m, s.scripted_altitude_m, s.scripted_period_s) == (2.0, 0.0, 40.0)
    assert (s.scripted_range_m, s.scripted_uncertainty) == (8.5, 0.2)
    assert s.scripted_noise == 0.05


def test_the_track_values_come_from_their_variables():
    env = {
        "TRACK_ACCEL_STD": "3",
        "TRACK_TIMEOUT_MS": "2500",
        "TRACK_ALTITUDE_M": "0",
        "TRACK_ALTITUDE_STD_M": "0.25",
    }
    s = load_settings(env)
    assert (s.track_accel_std, s.track_timeout_s) == (3.0, 2.5)
    assert (s.track_altitude_m, s.track_altitude_std_m) == (0.0, 0.25)


def test_seconds_are_derived_from_milliseconds():
    s = Settings(window_ms=250, state_period_ms=100, stale_after_ms=1500, detection_fresh_ms=3000)
    assert (s.state_period_s, s.stale_after_s, s.detection_fresh_s) == (0.1, 1.5, 3.0)


def test_window_frames_at_48_khz():
    assert Settings(window_ms=250).window_frames == 12_000


@pytest.mark.parametrize(
    ("env", "variable"),
    [
        ({"DISTANCE_ESTIMATOR": "neural"}, "DISTANCE_ESTIMATOR"),
        ({"DISTANCE_WINDOW_MS": "0"}, "DISTANCE_WINDOW_MS"),
        ({"STATE_PERIOD_MS": "-5"}, "STATE_PERIOD_MS"),
        ({"STALE_AFTER_MS": "1.5"}, "STALE_AFTER_MS"),
        ({"TRACK_ACCEL_STD": "0"}, "TRACK_ACCEL_STD"),
        ({"TRACK_TIMEOUT_MS": "0"}, "TRACK_TIMEOUT_MS"),
        ({"TRACK_ALTITUDE_M": "-1"}, "TRACK_ALTITUDE_M"),
        ({"TRACK_ALTITUDE_STD_M": "0"}, "TRACK_ALTITUDE_STD_M"),
        ({"DETECTION_FRESH_MS": "abc"}, "DETECTION_FRESH_MS"),
        ({"DETECTION_FRESH_MS": ""}, "DETECTION_FRESH_MS"),
        ({"FUSION_SPREAD_MS": "0"}, "FUSION_SPREAD_MS"),
        ({"SCRIPTED_OFFSET_EAST_M": "est"}, "SCRIPTED_OFFSET_EAST_M"),
        ({"SCRIPTED_OFFSET_NORTH_M": "nan"}, "SCRIPTED_OFFSET_NORTH_M"),
        ({"SCRIPTED_RADIUS_M": "0"}, "SCRIPTED_RADIUS_M"),
        ({"SCRIPTED_ALTITUDE_M": "-0.5"}, "SCRIPTED_ALTITUDE_M"),
        ({"SCRIPTED_PERIOD_S": "inf"}, "SCRIPTED_PERIOD_S"),
        ({"SCRIPTED_RANGE_M": "-3"}, "SCRIPTED_RANGE_M"),
        ({"SCRIPTED_UNCERTAINTY": "0"}, "SCRIPTED_UNCERTAINTY"),
        ({"SCRIPTED_NOISE": "-0.1"}, "SCRIPTED_NOISE"),
        ({"MODEL_UNCERTAINTY": "0"}, "MODEL_UNCERTAINTY"),
        ({"DISTANCE_ESTIMATOR": "model"}, "DISTANCE_MODEL_REPO"),
        ({"DISTANCE_ESTIMATOR": "model", "DISTANCE_MODEL_REPO": "team/model"},
         "DISTANCE_MODEL_REVISION"),
        ({"DISTANCE_ESTIMATOR": "model", "DISTANCE_MODEL_REPO": "team/model",
          "DISTANCE_MODEL_REVISION": "main"}, "DISTANCE_MODEL_REVISION"),
        ({"DISTANCE_ESTIMATOR": "model", "DISTANCE_MODEL_REVISION": SHA}, "DISTANCE_MODEL_REPO"),
    ],
)
def test_an_invalid_value_refuses_to_start_and_names_the_variable(env, variable):
    with pytest.raises(ValueError, match=variable):
        load_settings(env)


def test_an_invalid_value_is_refused_even_without_the_environment():
    with pytest.raises(ValueError, match="DISTANCE_WINDOW_MS"):
        Settings(window_ms=0)
    with pytest.raises(ValueError, match="DISTANCE_ESTIMATOR"):
        Settings(estimator="neural")


def test_one_millisecond_is_the_smallest_accepted_value():
    assert Settings(window_ms=1, state_period_ms=1).state_period_ms == 1


def test_the_model_comes_from_a_pinned_hugging_face_revision():
    env = {
        "DISTANCE_ESTIMATOR": "model",
        "DISTANCE_MODEL_REPO": "team/model",
        "DISTANCE_MODEL_REVISION": SHA,
        "HF_TOKEN": "hf_secret",
        "MODEL_UNCERTAINTY": "0.2",
    }
    s = load_settings(env)
    assert (s.model_repo, s.model_revision, s.hf_token) == ("team/model", SHA, "hf_secret")
    assert (s.model_dir, s.model_uncertainty) == (None, 0.2)


def test_a_local_bundle_needs_no_hugging_face_repo():
    s = load_settings({"DISTANCE_ESTIMATOR": "model", "DISTANCE_MODEL_DIR": "/srv/release"})
    assert s.model_dir == "/srv/release"


def test_an_empty_variable_counts_as_unset():
    assert load_settings({"HF_TOKEN": ""}).hf_token is None


def test_the_token_never_appears_in_logs_of_the_settings():
    assert "hf_secret" not in repr(Settings(hf_token="hf_secret"))
