"""③ branché : sélection des détections combinables, puis zone du drone via localiser_drone."""

import asyncio
import math
import random

import pytest

from api.fusion import Ranging, Tracker, fuse_once, locate, select
from api.profiles import Profile
from api.settings import Settings
from api.state import PhoneRegistry
from distance_estimation.estimator import AudioWindow, DistanceEstimate, Range
from distance_estimation.scripted import ScriptedEstimator, circle_near

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


def detect(sessions, detected, now):
    for profile, session in sessions.items():
        rng = Range(math.dist(DRONE, PHONES[profile]), 0.1) if profile in detected else None
        session.estimate(DistanceEstimate(profile, 0.0, rng), now)


def registry_and_sessions(*detected, now=0.0):
    registry = PhoneRegistry(PROFILES, Settings(estimator="scripted"))
    sessions = {p: registry.start(p, p, "edth.web-pcm.v1", lambda: None, now) for p in PHONES}
    detect(sessions, detected, now)
    return registry, sessions


def registry_with(*detected, now=0.0):
    return registry_and_sessions(*detected, now=now)[0]


def new_tracker():
    return Tracker(Settings(estimator="scripted"))


def fuse(registry, now=0.0, truth=None, tracker=None):
    settings = Settings(estimator="scripted")
    asyncio.run(fuse_once(registry, settings, truth, now, 100.0, tracker or new_tracker()))
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


def confirmed_track():
    """Trois téléphones détectent à chaque tick jusqu'à t = 0,5 : la piste est confirmée."""
    registry, sessions = registry_and_sessions("noe", "tristan", "maxence")
    tracker = new_tracker()
    fuse(registry, now=0.0, tracker=tracker)
    for now in (0.25, 0.5):
        detect(sessions, PHONES, now=now)
        fuse(registry, now=now, tracker=tracker)
    return registry, sessions, tracker


def test_the_track_is_shown_once_confirmed_where_the_drone_is():
    born = fuse(registry_with("noe", "tristan", "maxence"))
    # zone plus large que TRACK_MAX_RADIUS_M, mais les trois distances du tick confirment la piste
    assert born["zone"]["radius_m"] > 1.0 >= born["track"]["radius_m"]
    registry, _, tracker = confirmed_track()
    track = fuse(registry, now=0.5, tracker=tracker)["track"]
    assert set(track) == {"x_m", "y_m", "z_m", "vx_mps", "vy_mps", "radius_m", "z_min_m", "z_max_m"}
    assert math.dist((track["x_m"], track["y_m"]), DRONE[:2]) < track["radius_m"] <= 1.0
    assert track["z_min_m"] <= track["z_m"] <= track["z_max_m"]


def test_no_track_without_a_located_drone():
    assert fuse(registry_with("noe", "tristan"))["track"] is None


def test_the_track_goes_on_with_fewer_than_three_phones():
    registry, sessions, tracker = confirmed_track()
    detect(sessions, ("noe",), now=0.75)
    drone = fuse(registry, now=0.75, tracker=tracker)
    assert drone["status"] == "insufficient"
    assert math.dist((drone["track"]["x_m"], drone["track"]["y_m"]), DRONE[:2]) < 0.5


def test_each_detection_corrects_the_track_only_once():
    registry, sessions, tracker = confirmed_track()
    detect(sessions, PHONES, now=0.75)
    corrected = fuse(registry, now=0.75, tracker=tracker)["track"]["radius_m"]
    later = fuse(registry, now=1.0, tracker=tracker)["track"]["radius_m"]
    assert later > corrected  # sans détection nouvelle, l'incertitude ne fait que croître


def test_the_track_is_lost_without_detection():
    registry, _, tracker = confirmed_track()
    assert fuse(registry, now=0.75, tracker=tracker)["track"] is not None
    assert fuse(registry, now=1.75, tracker=tracker)["track"] is None


def simulate(noise, seconds=60.0, period=0.25):
    """Chaîne ②→③ sur la trajectoire scriptée par défaut : positions (vérité, zone brute, piste)
    à chaque tick où les deux existent."""
    settings = Settings(estimator="scripted")
    trajectory = circle_near(
        PHONES,
        settings.scripted_offset_east_m,
        settings.scripted_offset_north_m,
        settings.scripted_radius_m,
        settings.scripted_altitude_m,
        settings.scripted_period_s,
    )
    estimator = ScriptedEstimator(
        PHONES,
        trajectory,
        settings.scripted_range_m,
        settings.scripted_uncertainty,
        noise_rel=noise,
        rng=random.Random(7),
    )
    registry, sessions = registry_and_sessions()
    tracker = new_tracker()
    samples = []
    for k in range(int(seconds / period)):
        now = k * period
        for i, (profile, session) in enumerate(sessions.items()):
            t = now - i * period / len(PHONES)  # téléphones décalés entre eux
            session.estimate(estimator.estimate(AudioWindow(profile, profile, t, b"")), t)
        asyncio.run(fuse_once(registry, settings, trajectory.position, now, now, tracker))
        drone = registry.snapshot(now, server_time=0.0)["drone"]
        if drone["zone"] and drone["track"]:
            samples.append((trajectory.position(now), drone["zone"], drone["track"]))
    return samples


def rms_error(samples, which):
    errors = [
        math.dist((v["x_m"], v["y_m"]), truth[:2]) ** 2
        for truth, *views in samples
        for v in [views[which]]
    ]
    return math.sqrt(sum(errors) / len(errors))


def test_with_noisy_distances_the_track_is_closer_to_the_drone_than_the_raw_zone():
    samples = simulate(noise=0.05)
    assert len(samples) > 50
    raw, filtered = rms_error(samples, 0), rms_error(samples, 1)
    assert filtered < raw


def test_fusing_again_without_new_detection_changes_nothing():
    registry, sessions, tracker = confirmed_track()
    detect(sessions, PHONES, now=0.75)
    first = fuse(registry, now=1.0, tracker=tracker)["track"]
    assert first is not None
    assert fuse(registry, now=1.0, tracker=tracker)["track"] == first
