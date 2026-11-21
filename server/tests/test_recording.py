import wave

from conftest import sine

from app.recording import WavRecorder


def test_wav_data_is_byte_identical_to_received_pcm(tmp_path):
    samples = sine(seconds=0.5)
    raw = samples.tobytes()
    path = tmp_path / "nested" / "dir" / "s.wav"
    with WavRecorder(path) as rec:
        for offset in range(0, len(raw), 4800):
            rec.write(raw[offset : offset + 4800])
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 48000)
        assert wav.readframes(wav.getnframes()) == raw
    assert path.stat().st_size == 44 + len(raw)
