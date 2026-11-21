import hashlib
import json
import logging
import wave

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.main import app
from conftest import make_hello, packet, sine


@pytest.fixture
def client():
    return TestClient(app)


def open_session(ws, hello=None):
    hello = hello or make_hello()
    ws.send_text(json.dumps(hello))
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    assert ready["session_id"] == hello["session_id"]
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
    }
    sid = hello["session_id"][:8]
    assert f"event=session_start sid={sid} contract=edth.web-pcm.v1" in caplog.text
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
    with wave.open(str(tmp_path / f"{hello['session_id']}.wav"), "rb") as wav:
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
