import json

import pytest

from audio_capture.protocol import (
    End,
    Ping,
    ProtocolError,
    parse_control,
    parse_hello,
    parse_packet,
)
from conftest import make_hello


def raw(obj):
    return json.dumps(obj)


def test_valid_strict_hello_is_parsed(hello):
    parsed = parse_hello(raw(hello))
    assert str(parsed.session_id) == hello["session_id"]
    assert parsed.contract == "edth.web-pcm.v1"
    assert parsed.capture_settings == hello["capture_settings"]


def test_webkit_profile_is_accepted():
    hello = make_hello(
        settings={
            "capture_contract": "edth.web-pcm.webkit.v1",
            "noiseSuppression": None,
            "input_channels": None,
        }
    )
    assert parse_hello(raw(hello)).contract == "edth.web-pcm.webkit.v1"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"settings": {"capture_contract": "edth.web-pcm.v2"}}, "unknown_contract"),
        ({"settings": {"sample_rate": 44100}}, "invalid_format"),
        ({"settings": {"channels": 2}}, "invalid_format"),
        ({"settings": {"channels": True}}, "invalid_format"),
        ({"settings": {"sample_format": "f32le"}}, "invalid_format"),
        ({"settings": {"channel_selection": "mix"}}, "invalid_format"),
        ({"settings": {"recorder": "media_recorder"}}, "invalid_format"),
        ({"protocol": "crozidrone.audio-stream.v0"}, "unknown_protocol"),
        ({"session_id": "not-a-uuid"}, "invalid_hello"),
        ({"session_id": 12}, "invalid_hello"),
        ({"type": "ping"}, "invalid_hello"),
        ({"capture_settings": "nope"}, "invalid_hello"),
    ],
)
def test_invalid_hello_is_refused(overrides, code):
    with pytest.raises(ProtocolError) as err:
        parse_hello(raw(make_hello(**overrides)))
    assert err.value.code == code


@pytest.mark.parametrize("text", ["not json", "[]", "null"])
def test_non_object_hello_is_refused(text):
    with pytest.raises(ProtocolError) as err:
        parse_hello(text)
    assert err.value.code == "invalid_hello"


def test_packet_is_split_into_seq_and_pcm():
    pkt = parse_packet((7).to_bytes(4, "little") + b"\x01\x00\xff\xff")
    assert pkt.seq == 7
    assert pkt.pcm == b"\x01\x00\xff\xff"
    assert pkt.frames == 2


def test_seq_is_little_endian():
    assert parse_packet(b"\x01\x02\x00\x00\x00\x00").seq == 0x0201


@pytest.mark.parametrize(
    "data", [b"", b"\x00\x00\x00\x00", b"\x00\x00\x00\x00\x01", b"\x00\x00\x00\x00\x01\x02\x03"]
)
def test_short_or_odd_packet_is_refused(data):
    with pytest.raises(ProtocolError) as err:
        parse_packet(data)
    assert err.value.code == "invalid_packet"


def test_ping_and_end_are_parsed():
    assert parse_control(raw({"type": "ping", "t": 12.5})) == Ping(t=12.5)
    end = parse_control(raw({"type": "end", "reason": "manual", "frames": 10, "pcm_sha256": "ab"}))
    assert end == End(reason="manual", frames=10, pcm_sha256="ab")
    assert parse_control(raw({"type": "end", "reason": "error", "frames": 3})).pcm_sha256 is None
    assert parse_control(raw({"type": "end", "reason": "manual", "frames": 0})).frames == 0


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "hello"},
        {"type": "end", "reason": "oops", "frames": 1},
        {"type": "end", "reason": "manual", "frames": -1},
        {"type": "ping"},
        "x",
    ],
)
def test_unexpected_control_message_is_refused(msg):
    with pytest.raises(ProtocolError) as err:
        parse_control(raw(msg) if isinstance(msg, dict) else msg)
    assert err.value.code == "unexpected_message"
