"""Estimateur simulé : distance réelle entre un drone virtuel scripté et chaque téléphone."""

import math

import pytest

from distance_estimation.estimator import AudioWindow, Range
from distance_estimation.scripted import CircleTrajectory, ScriptedEstimator, circle_around

ORIGIN = (0.0, 0.0, 0.0)


def window(t, profile="noe"):
    return AudioWindow(profile=profile, session_id="sid", t=t, pcm=b"\x00\x00")


def test_the_trajectory_starts_east_of_the_center_and_turns_counterclockwise():
    circle = CircleTrajectory(center=(10.0, 5.0, 8.0), radius_m=2.0, period_s=40.0)
    assert circle.position(0.0) == pytest.approx((12.0, 5.0, 8.0))
    assert circle.position(10.0) == pytest.approx((10.0, 7.0, 8.0))
    assert circle.position(40.0) == pytest.approx((12.0, 5.0, 8.0))


def test_the_default_circle_is_centered_20_m_east_of_the_phones_10_m_high():
    circle = circle_around({"a": (0.0, 0.0, 0.0), "b": (2.0, 4.0, 0.0)})
    assert circle == CircleTrajectory(center=(21.0, 2.0, 10.0), radius_m=20.0, period_s=60.0)


def test_a_drone_in_range_gives_its_true_distance_and_the_default_uncertainty():
    circle = CircleTrajectory(center=(0.0, 0.0, 4.0), radius_m=3.0, period_s=60.0)
    estimator = ScriptedEstimator({"noe": ORIGIN}, circle, detection_range_m=30.0)
    estimate = estimator.estimate(window(t=0.0))
    assert estimate.profile == "noe" and estimate.t == 0.0
    assert estimate.range == Range(distance_m=pytest.approx(5.0), uncertainty_rel=0.10)
    assert estimate.drone


def test_a_drone_beyond_the_detection_range_is_not_detected():
    circle = CircleTrajectory(center=(0.0, 0.0, 0.0), radius_m=31.0, period_s=60.0)
    estimate = ScriptedEstimator({"noe": ORIGIN}, circle, detection_range_m=30.0).estimate(
        window(t=0.0)
    )
    assert estimate.range is None and not estimate.drone


def test_exactly_at_the_detection_range_counts_as_detected():
    circle = CircleTrajectory(center=(0.0, 0.0, 0.0), radius_m=30.0, period_s=60.0)
    estimate = ScriptedEstimator({"noe": ORIGIN}, circle, detection_range_m=30.0).estimate(
        window(t=0.0)
    )
    assert estimate.drone


def test_each_phone_gets_its_own_distance_to_the_same_drone():
    phones = {"noe": ORIGIN, "tristan": (6.0, 0.0, 0.0)}
    circle = CircleTrajectory(center=(0.0, 0.0, 0.0), radius_m=3.0, period_s=60.0)
    estimator = ScriptedEstimator(phones, circle)
    assert estimator.estimate(window(0.0, "noe")).range.distance_m == pytest.approx(3.0)
    assert estimator.estimate(window(0.0, "tristan")).range.distance_m == pytest.approx(3.0)
    quarter = estimator.estimate(window(15.0, "tristan")).range.distance_m
    assert quarter == pytest.approx(math.hypot(6.0, 3.0))


def test_by_default_the_drone_comes_in_and_out_of_range_of_the_team_phones():
    phones = {"noe": (2.06, 9.66, 0.0), "maxence": (2.06, 11.86, 0.0)}
    estimator = ScriptedEstimator(phones)
    detected = [estimator.estimate(window(float(t))).drone for t in range(60)]
    assert any(detected) and not all(detected)
