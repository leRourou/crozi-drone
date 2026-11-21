"""Découpage du PCM d'une session en fenêtres contiguës de taille fixe."""

from distance_estimation.windows import WindowAccumulator


def pcm(frames, value=0):
    return int(value).to_bytes(2, "little", signed=True) * frames


def test_no_window_until_enough_samples_arrived():
    acc = WindowAccumulator("noe", "sid", frames=4)
    assert acc.add(pcm(3), t=1.0) == []


def test_a_window_carries_the_session_and_the_arrival_time_of_its_last_packet():
    acc = WindowAccumulator("noe", "sid", frames=4)
    acc.add(pcm(3, 1), t=1.0)
    [window] = acc.add(pcm(2, 2), t=2.0)
    assert (window.profile, window.session_id, window.t) == ("noe", "sid", 2.0)
    assert window.pcm == pcm(3, 1) + pcm(1, 2)


def test_the_remainder_starts_the_next_window_without_loss():
    acc = WindowAccumulator("noe", "sid", frames=4)
    acc.add(pcm(5, 1), t=1.0)
    [window] = acc.add(pcm(3, 2), t=2.0)
    assert window.pcm == pcm(1, 1) + pcm(3, 2)


def test_one_packet_can_complete_several_windows():
    acc = WindowAccumulator("noe", "sid", frames=2)
    windows = acc.add(pcm(5), t=3.0)
    assert [len(w.pcm) for w in windows] == [4, 4]
