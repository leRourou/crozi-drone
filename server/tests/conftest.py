import copy
import uuid

import numpy as np
import pytest

BASE_SETTINGS = {
    "capture_contract": "edth.web-pcm.v1",
    "recorder": "audio_worklet_pcm",
    "echoCancellation": False,
    "noiseSuppression": False,
    "autoGainControl": False,
    "sample_rate": 48000,
    "channels": 1,
    "channel_selection": "first",
    "input_channels": 1,
    "sample_format": "pcm_s16le",
    "browser": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari",
    "microphone_label": "Default",
    "track_settings": {"echoCancellation": False, "channelCount": 1},
    "system_processing": "unverified",
}


def make_hello(**overrides):
    settings = copy.deepcopy(BASE_SETTINGS)
    settings.update(overrides.pop("settings", {}))
    hello = {
        "type": "hello",
        "protocol": "thc.audio-stream.v1",
        "session_id": str(uuid.uuid4()),
        "capture_settings": settings,
        "captured_at": "2026-11-21T10:00:00.000Z",
        "user_agent": settings["browser"],
    }
    hello.update(overrides)
    return hello


def sine(freq=440.0, seconds=1.0, amplitude=0.5, rate=48000):
    t = np.arange(int(seconds * rate)) / rate
    return np.round(amplitude * 32767 * np.sin(2 * np.pi * freq * t)).astype("<i2")


def packet(seq, samples):
    return int(seq).to_bytes(4, "little") + np.asarray(samples, dtype="<i2").tobytes()


@pytest.fixture
def hello():
    return make_hello()
