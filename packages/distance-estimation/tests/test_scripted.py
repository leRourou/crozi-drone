"""Estimateur simulé : distance réelle entre un drone virtuel scripté et chaque téléphone."""

import math

import pytest

from distance_estimation.estimator import AudioWindow, Range
from distance_estimation.scripted import CircleTrajectory, ScriptedEstimator, circle_near

ORIGIN = (0.0, 0.0, 0.0)


def window(t, profile="noe"):
    return AudioWindow(profile=profile, session_id="sid", t=t, pcm=b"\x00\x00")


def estimator(phones, circle, detection_range_m=30.0, uncertainty_rel=0.10):
    return ScriptedEstimator(phones, circle, detection_range_m, uncertainty_rel)


def test_the_trajectory_starts_east_of_the_center_and_turns_counterclockwise():
    circle = CircleTrajectory(center=(10.0, 5.0, 8.0), radius_m=2.0, period_s=40.0)
    assert circle.position(0.0) == pytest.approx((12.0, 5.0, 8.0))
    assert circle.position(10.0) == pytest.approx((10.0, 7.0, 8.0))
    assert circle.position(40.0) == pytest.approx((12.0, 5.0, 8.0))


def test_the_circle_is_placed_relative_to_the_phones_barycentre_y_pointing_south():
    phones = {"a": (0.0, 0.0, 0.0), "b": (2.0, 4.0, 0.0)}
    circle = circle_near(
        phones, east_m=0.5, north_m=3.0, radius_m=2.5, altitude_m=1.5, period_s=20.0
    )
    assert circle == CircleTrajectory(center=(1.5, -1.0, 1.5), radius_m=2.5, period_s=20.0)


def test_a_drone_in_range_gives_its_true_distance_and_the_given_uncertainty():
    circle = CircleTrajectory(center=(0.0, 0.0, 4.0), radius_m=3.0, period_s=60.0)
    estimate = estimator({"noe": ORIGIN}, circle, uncertainty_rel=0.2).estimate(window(t=0.0))
    assert estimate.profile == "noe" and estimate.t == 0.0
    assert estimate.range == Range(distance_m=pytest.approx(5.0), uncertainty_rel=0.2)
    assert estimate.drone


def test_a_drone_beyond_the_detection_range_is_not_detected():
    circle = CircleTrajectory(center=(0.0, 0.0, 0.0), radius_m=31.0, period_s=60.0)
    estimate = estimator({"noe": ORIGIN}, circle, detection_range_m=30.0).estimate(window(t=0.0))
    assert estimate.range is None and not estimate.drone


def test_exactly_at_the_detection_range_counts_as_detected():
    circle = CircleTrajectory(center=(0.0, 0.0, 0.0), radius_m=30.0, period_s=60.0)
    estimate = estimator({"noe": ORIGIN}, circle, detection_range_m=30.0).estimate(window(t=0.0))
    assert estimate.drone


def test_each_phone_gets_its_own_distance_to_the_same_drone():
    phones = {"noe": ORIGIN, "tristan": (6.0, 0.0, 0.0)}
    circle = CircleTrajectory(center=(0.0, 0.0, 0.0), radius_m=3.0, period_s=60.0)
    scripted = estimator(phones, circle)
    assert scripted.estimate(window(0.0, "noe")).range.distance_m == pytest.approx(3.0)
    assert scripted.estimate(window(0.0, "tristan")).range.distance_m == pytest.approx(3.0)
    quarter = scripted.estimate(window(15.0, "tristan")).range.distance_m
    assert quarter == pytest.approx(math.hypot(6.0, 3.0))


def test_the_true_drone_position_is_exposed_for_checking_the_chain():
    circle = CircleTrajectory(center=(1.0, 2.0, 1.5), radius_m=3.0, period_s=60.0)
    assert estimator({"noe": ORIGIN}, circle).drone_position(15.0) == pytest.approx((1.0, 5.0, 1.5))
