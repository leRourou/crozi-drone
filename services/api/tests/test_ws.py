import hashlib
import json
import logging
import math
import wave

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.main import create_app
from api.profiles import load_profiles
from api.settings import Settings
from conftest import make_hello, packet, sine


def fresh_app(**settings):
    """Une application neuve par test : le registre d'état ne fuit pas d'un test à l'autre."""
    return create_app(None, load_profiles(), Settings(**settings))


@pytest.fixture
def client():
    return TestClient(fresh_app())


def open_session(ws, hello=None):
    hello = hello or make_hello()
    ws.send_text(json.dumps(hello))
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    assert ready["session_id"] == hello["session_id"]
    assert ready["profile"] == hello["profile"]
    return hello


def send_audio(ws, samples, size=2400):
    for seq, offset in enumerate(range(0, len(samples), size)):
        ws.send_bytes(packet(seq, samples[offset : offset + size]))


def receive_until(ws, kind):
    while True:
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg


def expect_error(ws, code):
    msg = receive_until(ws, "error")
    assert msg["code"] == code
    with pytest.raises(WebSocketDisconnect):
        ws.receive_json()


def test_full_session_ends_with_matching_ack(client, caplog):
    samples = sine(seconds=0.5)
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    with client.websocket_connect("/ws/audio") as ws:
        hello = open_session(ws)
        send_audio(ws, samples)
        digest = hashlib.sha256(samples.tobytes()).hexdigest()
        ws.send_text(
            json.dumps(
                {"type": "end", "reason": "manual", "frames": len(samples), "pcm_sha256": digest}
            )
        )
        ack = receive_until(ws, "end_ack")
    assert ack == {
        "type": "end_ack",
        "frames_received": len(samples),
        "pcm_sha256": digest,
        "match": True,
        "profile": "tristan",
    }
    sid = hello["session_id"][:8]
    assert f"event=session_start sid={sid} profile=tristan contract=edth.web-pcm.v1" in caplog.text
    [end] = [r.message for r in caplog.records if "event=session_end" in r.message]
    assert f"sid={sid} profile=tristan" in end
    assert "match=✅" in caplog.text and "reason=manual" in caplog.text


def test_ping_gets_pong(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_text(json.dumps({"type": "ping", "t": 123.5}))
        assert receive_until(ws, "pong") == {"type": "pong", "t": 123.5}


def test_unknown_contract_is_refused(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello(settings={"capture_contract": "custom"})))
        expect_error(ws, "unknown_contract")


def test_unknown_profile_is_refused(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello(profile="bob")))
        expect_error(ws, "unknown_profile")


def test_binary_before_hello_is_refused(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(packet(0, [0, 0]))
        expect_error(ws, "invalid_hello")


def test_odd_packet_closes_session(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(b"\x00\x00\x00\x00\x01\x02\x03")
        expect_error(ws, "invalid_packet")


def test_seq_gap_closes_session_with_discontinuity_log(client, caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(packet(0, [1, 2]))
        ws.send_bytes(packet(2, [3, 4]))
        expect_error(ws, "discontinuity")
    assert "event=discontinuity" in caplog.text and "expected=1 got=2" in caplog.text


def test_client_disconnect_is_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(packet(0, [1, 2]))
    assert "event=session_end" in caplog.text and "reason=disconnect" in caplog.text


def test_stats_are_pushed_every_second(client):
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        send_audio(ws, sine(seconds=0.2))
        stats = receive_until(ws, "stats")
    assert stats["audio_s"] == pytest.approx(0.2)
    assert set(stats) >= {
        "packets_per_s",
        "rt_ratio",
        "kbps",
        "peak_dbfs",
        "rms_dbfs",
        "max_gap_ms",
        "gaps",
    }


def test_saved_session_wav_matches_received_bytes(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SAVE_SESSIONS", "1")
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path))
    samples = sine(seconds=0.3)
    with client.websocket_connect("/ws/audio") as ws:
        hello = open_session(ws)
        send_audio(ws, samples)
        ws.send_text(
            json.dumps(
                {
                    "type": "end",
                    "reason": "manual",
                    "frames": len(samples),
                    "pcm_sha256": hashlib.sha256(samples.tobytes()).hexdigest(),
                }
            )
        )
        receive_until(ws, "end_ack")
    with wave.open(str(tmp_path / f"tristan_{hello['session_id']}.wav"), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == samples.tobytes()


def test_match_is_logged_at_info_and_mismatch_at_warning(client, caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    samples = sine(seconds=0.1)
    good = hashlib.sha256(samples.tobytes()).hexdigest()
    for digest, level in ((good, logging.INFO), ("0" * 64, logging.WARNING)):
        caplog.clear()
        with client.websocket_connect("/ws/audio") as ws:
            open_session(ws)
            send_audio(ws, samples)
            ws.send_text(
                json.dumps(
                    {
                        "type": "end",
                        "reason": "manual",
                        "frames": len(samples),
                        "pcm_sha256": digest,
                    }
                )
            )
            receive_until(ws, "end_ack")
        [end] = [r for r in caplog.records if "event=session_end" in r.message]
        assert end.levelno == level


def test_webkit_profile_is_logged_as_a_warning(client, caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws, make_hello(settings={"capture_contract": "edth.web-pcm.webkit.v1"}))
    warnings = [r for r in caplog.records if "event=webkit_profile" in r.message]
    assert [r.levelno for r in warnings] == [logging.WARNING]


def test_strict_profile_has_no_webkit_warning(client, caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
    assert "webkit_profile" not in caplog.text


def test_error_end_without_client_hash_is_logged_as_not_applicable(client, caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    with client.websocket_connect("/ws/audio") as ws:
        open_session(ws)
        ws.send_bytes(packet(0, [1, 2]))
        ws.send_text(json.dumps({"type": "end", "reason": "error", "frames": 2}))
        ack = receive_until(ws, "end_ack")
    assert ack["match"] is False
    assert "match=n/a" in caplog.text and "reason=error" in caplog.text


def test_state_lists_every_contract_phone_and_no_estimator_by_default(client):
    with client.websocket_connect("/ws/state") as ws:
        state = ws.receive_json()
    assert state["type"] == "state" and state["estimator"] == "none"
    assert [p["profile"] for p in state["phones"]] == ["noe", "tristan", "maxence"]
    assert {p["status"] for p in state["phones"]} == {"never_seen"}


def phone_state(client, profile):
    with client.websocket_connect("/ws/state") as ws:
        phones = ws.receive_json()["phones"]
    [entry] = [p for p in phones if p["profile"] == profile]
    return entry


def test_state_shows_a_phone_streaming_then_offline():
    with TestClient(fresh_app()) as client:
        with client.websocket_connect("/ws/audio") as ws:
            hello = open_session(ws, make_hello(profile="maxence"))
            send_audio(ws, sine(seconds=0.1))
            entry = phone_state(client, "maxence")
            assert (entry["status"], entry["session_id"]) == ("streaming", hello["session_id"])
            assert entry["detection"] is None
        assert phone_state(client, "maxence")["status"] == "offline"


def test_a_newer_session_on_the_same_phone_stops_the_older_one():
    with TestClient(fresh_app()) as client, client.websocket_connect("/ws/audio") as old:
        open_session(old, make_hello(profile="noe"))
        with client.websocket_connect("/ws/audio") as new:
            hello = open_session(new, make_hello(profile="noe"))
            expect_error(old, "session_replaced")
            assert phone_state(client, "noe")["session_id"] == hello["session_id"]


def test_the_scripted_estimator_reports_a_detection_per_received_window():
    with TestClient(fresh_app(estimator="scripted")) as client:
        assert phone_state(client, "tristan")["detection"] is None
        with client.websocket_connect("/ws/audio") as ws:
            open_session(ws, make_hello(profile="tristan"))
            send_audio(ws, sine(seconds=0.5))
            ws.send_text(json.dumps({"type": "ping", "t": 1}))
            receive_until(ws, "pong")  # les paquets précédents ont été traités
            detection = phone_state(client, "tristan")["detection"]
    assert detection["fresh"] is True
    assert detection["drone"] is (detection["distance_m"] is not None)


def test_three_listening_phones_locate_the_simulated_drone():
    # Portée immense : les trois téléphones entendent toujours le drone virtuel.
    app = fresh_app(estimator="scripted", state_period_ms=20, scripted_range_m=1000.0)
    with TestClient(app) as client:
        sockets = [client.websocket_connect("/ws/audio") for _ in range(3)]
        for ws, profile in zip(sockets, ["noe", "tristan", "maxence"], strict=True):
            ws.__enter__()
            open_session(ws, make_hello(profile=profile))
            send_audio(ws, sine(seconds=0.25))
            ws.send_text(json.dumps({"type": "ping", "t": 1}))
            receive_until(ws, "pong")
        with client.websocket_connect("/ws/state") as state_ws:
            drone = None
            for _ in range(50):
                drone = state_ws.receive_json()["drone"]
                if drone["status"] == "located":
                    break
        for ws in sockets:
            ws.__exit__(None, None, None)
    assert (drone["status"], drone["detecting"]) == ("located", 3)
    truth, zone = drone["truth"], drone["zone"]
    assert math.dist((truth["x_m"], truth["y_m"]), (zone["x_m"], zone["y_m"])) < 3.0


def test_without_estimator_the_state_has_no_drone_view(client):
    with client.websocket_connect("/ws/state") as ws:
        assert ws.receive_json()["drone"] is None


def test_scripted_noise_reaches_the_simulated_distances():
    from api.main import make_estimation
    from distance_estimation.estimator import AudioWindow

    profiles = load_profiles()
    window = AudioWindow("noe", "sid", 0.0, b"")
    exact = make_estimation(Settings(estimator="scripted", scripted_range_m=100.0), profiles)
    noisy = make_estimation(
        Settings(estimator="scripted", scripted_range_m=100.0, scripted_noise=0.05), profiles
    )
    assert len({exact.estimator.estimate(window).range.distance_m for _ in range(5)}) == 1
    assert len({noisy.estimator.estimate(window).range.distance_m for _ in range(5)}) == 5


def test_state_is_pushed_every_state_period():
    with TestClient(fresh_app(state_period_ms=20)) as client, client.websocket_connect(
        "/ws/state"
    ) as ws:
        times = [ws.receive_json()["server_time"] for _ in range(3)]
    assert 0.015 <= times[2] - times[1] < 0.5


def test_a_window_is_estimated_as_soon_as_it_is_complete():
    app = fresh_app(estimator="scripted", window_ms=100)
    with TestClient(app) as client, client.websocket_connect("/ws/audio") as ws:
        open_session(ws, make_hello(profile="noe"))
        send_audio(ws, sine(seconds=0.1), size=4800)
        ws.send_text(json.dumps({"type": "ping", "t": 1}))
        receive_until(ws, "pong")
        detection = phone_state(client, "noe")["detection"]
    assert detection is not None
