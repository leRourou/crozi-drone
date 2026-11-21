import hashlib
import json

import numpy as np
import pytest

from audio_capture.protocol import End, Packet, ProtocolError, parse_hello
from audio_capture.session import StreamSession
from conftest import make_hello, sine


def session(**kw):
    return StreamSession(parse_hello(json.dumps(make_hello())), started_at=0.0, **kw)


def packets(samples, size=2400):
    return [
        Packet(seq=i, pcm=samples[o : o + size].tobytes())
        for i, o in enumerate(range(0, len(samples), size))
    ]


def test_matching_end_is_acknowledged():
    samples = sine(seconds=0.3)
    s = session()
    for i, pkt in enumerate(packets(samples)):
        s.accept(pkt, now=0.05 * (i + 1))
    digest = hashlib.sha256(samples.tobytes()).hexdigest()
    ack = s.finish(End(reason="manual", frames=len(samples), pcm_sha256=digest))
    assert ack.frames_received == len(samples)
    assert ack.pcm_sha256 == digest
    assert ack.match is True


def test_incremental_hash_detects_one_flipped_sample():
    samples = sine(seconds=0.1)
    s = session()
    for pkt in packets(samples):
        s.accept(pkt, now=0.1)
    altered = samples.copy()
    altered[-1] ^= 1
    ack = s.finish(
        End(
            reason="manual",
            frames=len(samples),
            pcm_sha256=hashlib.sha256(altered.tobytes()).hexdigest(),
        )
    )
    assert ack.match is False


def test_frame_count_mismatch_is_not_a_match():
    samples = sine(seconds=0.1)
    s = session()
    for pkt in packets(samples):
        s.accept(pkt, now=0.1)
    digest = hashlib.sha256(samples.tobytes()).hexdigest()
    assert s.finish(End(reason="limit", frames=len(samples) + 1, pcm_sha256=digest)).match is False


def test_end_without_client_hash_is_not_a_match():
    s = session()
    s.accept(Packet(seq=0, pcm=b"\x00\x00"), now=0.1)
    assert s.finish(End(reason="error", frames=1, pcm_sha256=None)).match is False


def test_seq_gap_is_a_discontinuity():
    s = session()
    s.accept(Packet(seq=0, pcm=b"\x00\x00"), now=0.1)
    with pytest.raises(ProtocolError) as err:
        s.accept(Packet(seq=2, pcm=b"\x00\x00"), now=0.2)
    assert err.value.code == "discontinuity"
    assert "expected=1" in err.value.message and "got=2" in err.value.message


def test_first_packet_must_have_seq_zero():
    with pytest.raises(ProtocolError):
        session().accept(Packet(seq=1, pcm=b"\x00\x00"), now=0.1)


def test_received_bytes_are_forwarded_untouched_to_the_sink():
    received = []
    s = session(sink=received.append)
    samples = sine(seconds=0.2)
    for pkt in packets(samples):
        s.accept(pkt, now=0.1)
    assert b"".join(received) == samples.tobytes()


def test_frames_received_counts_samples():
    s = session()
    s.accept(Packet(seq=0, pcm=np.zeros(5, dtype="<i2").tobytes()), now=0.1)
    assert s.frames_received == 5
