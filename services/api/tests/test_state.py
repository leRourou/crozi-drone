"""État général des téléphones : registre en mémoire, horloge injectée."""

import pytest

from api.profiles import Profile
from api.settings import Settings
from api.state import PhoneRegistry
from distance_estimation.estimator import DistanceEstimate, Range

PROFILES = (
    Profile("noe", "Téléphone de Noé", 2.06, 9.66, 0.0),
    Profile("tristan", "Téléphone de Tristan", 4.0, 10.76, 0.0),
)


def phone(registry, profile, now):
    phones = registry.snapshot(now, server_time=0.0)["phones"]
    [entry] = [p for p in phones if p["profile"] == profile]
    return entry


def start(registry, profile="noe", sid="s1", now=0.0, replaced=None):
    return registry.start(profile, sid, "edth.web-pcm.v1", replaced or (lambda: None), now)


@pytest.fixture
def registry():
    return PhoneRegistry(PROFILES, Settings(estimator="scripted"))


def test_every_contract_phone_is_listed_never_seen_before_any_session(registry):
    state = registry.snapshot(5.0, server_time=1795000000.0)
    assert state["type"] == "state"
    assert state["server_time"] == 1795000000.0
    assert state["estimator"] == "scripted"
    assert state["drone"] is None
    assert state["phones"][0] == {
        "profile": "noe",
        "label": "Téléphone de Noé",
        "position_m": {"x": 2.06, "y": 9.66, "z": 0.0},
        "status": "never_seen",
        "session_id": None,
        "contract": None,
        "last_seen_age_s": None,
        "rt_ratio": None,
        "rms_dbfs": None,
        "detection": None,
    }
    assert [p["profile"] for p in state["phones"]] == ["noe", "tristan"]


def test_the_registry_knows_the_contract_ids(registry):
    assert registry.ids == frozenset({"noe", "tristan"})


def test_a_started_session_is_streaming_with_its_identity(registry):
    start(registry, now=10.0)
    entry = phone(registry, "noe", 10.5)
    assert entry["status"] == "streaming"
    assert (entry["session_id"], entry["contract"]) == ("s1", "edth.web-pcm.v1")
    assert entry["last_seen_age_s"] == pytest.approx(0.5)
    assert phone(registry, "tristan", 10.5)["status"] == "never_seen"


def test_a_session_without_packets_for_more_than_a_second_is_stale(registry):
    session = start(registry, now=10.0)
    assert phone(registry, "noe", 11.0)["status"] == "streaming"
    assert phone(registry, "noe", 11.1)["status"] == "stale"
    session.packet(11.1)
    assert phone(registry, "noe", 11.2)["status"] == "streaming"


def test_reception_stats_are_shown_while_streaming(registry):
    start(registry).stats(rt_ratio=0.99, rms_dbfs=-42.0)
    entry = phone(registry, "noe", 0.1)
    assert (entry["rt_ratio"], entry["rms_dbfs"]) == (0.99, -42.0)


def test_an_ended_session_leaves_the_phone_offline_with_its_last_seen_age(registry):
    session = start(registry, now=10.0)
    session.packet(12.0)
    session.stats(rt_ratio=1.0, rms_dbfs=-40.0)
    session.estimate(DistanceEstimate("noe", 0.0, Range(5.0, 0.1)), now=12.0)
    session.end(13.0)
    entry = phone(registry, "noe", 20.0)
    assert entry["status"] == "offline"
    assert entry["last_seen_age_s"] == pytest.approx(7.0)
    assert entry["session_id"] is None and entry["contract"] is None
    assert entry["rt_ratio"] is None and entry["detection"] is None


def test_a_detection_shows_distance_uncertainty_and_freshness(registry):
    session = start(registry)
    session.estimate(DistanceEstimate("noe", 0.0, Range(12.3, 0.1)), now=1.0)
    assert phone(registry, "noe", 3.0)["detection"] == {
        "drone": True,
        "distance_m": 12.3,
        "uncertainty_rel": 0.1,
        "age_s": pytest.approx(2.0),
        "fresh": True,
    }
    session.packet(3.1)
    assert phone(registry, "noe", 3.1)["detection"]["fresh"] is False


def test_no_drone_is_reported_as_detected_false_without_distance(registry):
    session = start(registry)
    session.estimate(DistanceEstimate("noe", 0.0, None), now=0.0)
    detection = phone(registry, "noe", 0.0)["detection"]
    assert (detection["drone"], detection["distance_m"], detection["uncertainty_rel"]) == (
        False,
        None,
        None,
    )


def test_a_new_session_on_the_same_phone_replaces_the_old_one(registry):
    replaced = []
    old = start(registry, sid="old", replaced=lambda: replaced.append("old"))
    start(registry, sid="new", now=1.0)
    assert replaced == ["old"]
    old.packet(5.0)
    old.end(5.0)
    entry = phone(registry, "noe", 2.5)
    assert (entry["status"], entry["session_id"]) == ("stale", "new")


def test_a_new_session_on_another_phone_replaces_nothing(registry):
    replaced = []
    start(registry, "noe", replaced=lambda: replaced.append("noe"))
    start(registry, "tristan")
    assert replaced == []


def test_thresholds_come_from_the_settings():
    settings = Settings(estimator="scripted", stale_after_ms=500, detection_fresh_ms=300)
    registry = PhoneRegistry(PROFILES, settings)
    session = start(registry)
    session.estimate(DistanceEstimate("noe", 0.0, None), now=0.0)
    assert phone(registry, "noe", 0.3)["detection"]["fresh"] is True
    assert phone(registry, "noe", 0.31)["detection"]["fresh"] is False
    assert phone(registry, "noe", 0.5)["status"] == "streaming"
    assert phone(registry, "noe", 0.51)["status"] == "stale"
