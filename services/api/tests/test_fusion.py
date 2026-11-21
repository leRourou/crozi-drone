"""③ branché : sélection des détections combinables, puis zone du drone via localiser_drone."""

import asyncio
import math

import pytest

from api.fusion import Ranging, fuse_once, locate, select
from api.profiles import Profile
from api.settings import Settings
from api.state import PhoneRegistry
from distance_estimation.estimator import DistanceEstimate, Range

PHONES = {"noe": (2.06, 9.66, 0.0), "tristan": (4.0, 10.76, 0.0), "maxence": (2.06, 11.86, 0.0)}
PROFILES = tuple(Profile(pid, pid, *pos) for pid, pos in PHONES.items())
DRONE = (3.0, 8.0, 1.5)


def ranging(profile, received_at=0.0, distance=None, uncertainty=0.1):
    position = PHONES[profile]
    distance = math.dist(DRONE, position) if distance is None else distance
    return Ranging(profile, position, distance, uncertainty, received_at)


def test_select_keeps_fresh_rangings_close_in_time_to_the_newest():
    rangings = [
        ranging("noe", received_at=7.0),  # trop vieille : 3 s
        ranging("tristan", received_at=9.4),  # 0,6 s avant la plus récente
        ranging("maxence", received_at=10.0),
    ]
    kept = select(rangings, now=10.0, fresh_s=2.0, spread_s=0.5)
    assert [r.profile for r in kept] == ["maxence"]
    kept = select(rangings, now=10.0, fresh_s=2.0, spread_s=0.6)
    assert [r.profile for r in kept] == ["tristan", "maxence"]


def test_select_limits_are_inclusive_and_nothing_gives_nothing():
    rangings = [ranging("noe", received_at=8.0), ranging("tristan", received_at=8.5)]
    assert len(select(rangings, now=10.0, fresh_s=2.0, spread_s=0.5)) == 2
    assert select([], now=10.0, fresh_s=2.0, spread_s=0.5) == []


def test_locate_finds_a_zone_containing_the_true_drone():
    zone = locate([ranging(p) for p in PHONES])
    assert math.dist((zone["x_m"], zone["y_m"]), DRONE[:2]) <= zone["radius_m"]
    assert zone["z_min_m"] <= DRONE[2] <= zone["z_max_m"]
    assert zone["z_min_m"] <= zone["z_m"] <= zone["z_max_m"]
    assert (zone["tolerance"], zone["degraded"]) == (0.1, False)


def test_locate_uses_the_largest_uncertainty_as_tolerance():
    rangings = [
        ranging("noe", uncertainty=0.05),
        ranging("tristan"),
        ranging("maxence", uncertainty=0.2),
    ]
    assert locate(rangings)["tolerance"] == 0.2


def test_locate_returns_none_for_incompatible_distances():
    assert locate([ranging(p, distance=0.1) for p in PHONES]) is None


def registry_with(*detected, now=0.0, settings=None):
    registry = PhoneRegistry(PROFILES, settings or Settings(estimator="scripted"))
    for profile in PHONES:
        session = registry.start(profile, profile, "edth.web-pcm.v1", lambda: None, now)
        rng = Range(math.dist(DRONE, PHONES[profile]), 0.1) if profile in detected else None
        session.estimate(DistanceEstimate(profile, 0.0, rng), now)
    return registry


def fuse(registry, now=0.0, truth=None):
    asyncio.run(fuse_once(registry, Settings(estimator="scripted"), truth, now, wall=100.0))
    return registry.snapshot(now, server_time=0.0)["drone"]


def test_three_detecting_phones_locate_the_drone():
    drone = fuse(registry_with("noe", "tristan", "maxence"))
    assert (drone["status"], drone["detecting"]) == ("located", 3)
    zone = drone["zone"]
    assert math.dist((zone["x_m"], zone["y_m"]), DRONE[:2]) <= zone["radius_m"]


def test_fewer_than_three_detecting_phones_give_no_position():
    drone = fuse(registry_with("noe", "tristan"))
    assert (drone["status"], drone["detecting"], drone["zone"]) == ("insufficient", 2, None)


def test_no_detecting_phone():
    drone = fuse(registry_with())
    assert (drone["status"], drone["detecting"], drone["zone"]) == ("no_detection", 0, None)


def test_incompatible_distances_are_reported_as_inconsistent():
    registry = PhoneRegistry(PROFILES, Settings(estimator="scripted"))
    for profile in PHONES:
        session = registry.start(profile, profile, "edth.web-pcm.v1", lambda: None, 0.0)
        session.estimate(DistanceEstimate(profile, 0.0, Range(0.1, 0.1)), 0.0)
    drone = fuse(registry)
    assert (drone["status"], drone["detecting"], drone["zone"]) == ("inconsistent", 3, None)


def test_the_true_position_is_given_in_simulation_only():
    assert fuse(registry_with(), truth=None)["truth"] is None
    truth = fuse(registry_with(), truth=lambda t: (t / 100, 2.0, 1.5))["truth"]
    assert truth == {"x_m": 1.0, "y_m": 2.0, "z_m": 1.5}


def test_the_drone_view_ages_with_time():
    registry = registry_with("noe", "tristan", "maxence")
    fuse(registry, now=10.0)
    assert registry.snapshot(10.75, server_time=0.0)["drone"]["age_s"] == pytest.approx(0.75)


def test_without_estimator_there_is_no_drone_view():
    registry = PhoneRegistry(PROFILES, Settings())
    assert registry.snapshot(0.0, server_time=0.0)["drone"] is None
