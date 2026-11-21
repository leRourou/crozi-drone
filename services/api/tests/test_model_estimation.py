"""DISTANCE_ESTIMATOR=model : bundle local ou Hugging Face, chargé au démarrage, sans repli."""

import json
import logging
import shutil

import pytest
from fastapi.testclient import TestClient

from api.main import create_app, make_estimation
from api.model_fetch import resolve_bundle
from api.profiles import load_profiles
from api.settings import Settings
from conftest import bundle_signal, make_hello, packet

SHA = "811bafcd6fa0e94b287b37133d8d6331b50eb3e3"


def no_fetch(*args):
    raise AssertionError("aucun téléchargement attendu")


def test_a_local_bundle_is_used_as_is(tmp_path):
    settings = Settings(estimator="model", model_dir=str(tmp_path))
    assert resolve_bundle(settings, fetch=no_fetch) == tmp_path


def test_otherwise_the_pinned_revision_is_fetched_with_the_token(tmp_path):
    calls = []

    def fetch(repo, revision, token, release):
        calls.append((repo, revision, token, release))
        return tmp_path

    settings = Settings(
        estimator="model", model_repo="team/model", model_revision=SHA,
        model_release="edth.audio.24k-1s.r0", hf_token="hf_x",
    )
    assert resolve_bundle(settings, fetch=fetch) == tmp_path / "edth.audio.24k-1s.r0"
    assert calls == [("team/model", SHA, "hf_x", "edth.audio.24k-1s.r0")]


def test_the_model_estimation_takes_one_period_per_chunk_without_simulated_truth(
    model_bundle, caplog
):
    settings = Settings(estimator="model", model_dir=str(model_bundle), model_uncertainty=0.2)
    with caplog.at_level(logging.INFO, logger="crozidrone.audio"):
        estimation = make_estimation(settings, load_profiles())
    assert (estimation.window_frames, estimation.truth) == (4800, None)  # MODEL_PERIOD_MS=100
    assert "event=model_loaded release=test.48k-w100.r0 source=local" in caplog.text
    assert "period_ms=100" in caplog.text


def test_the_estimate_period_sets_the_chunk_size(model_bundle):
    settings = Settings(estimator="model", model_dir=str(model_bundle), model_period_ms=20)
    assert make_estimation(settings, load_profiles()).window_frames == 960


def test_a_period_that_is_not_a_whole_number_of_release_steps_stops_the_server(model_bundle):
    settings = Settings(estimator="model", model_dir=str(model_bundle), model_period_ms=30)
    with pytest.raises(ValueError, match="20 ms"):
        create_app(None, load_profiles(), settings)


def test_a_broken_bundle_stops_the_server_from_starting(model_bundle, tmp_path):
    broken = shutil.copytree(model_bundle, tmp_path / "bundle")
    manifest = json.loads((broken / "manifest.json").read_text())
    manifest["contract"] = "edth.model-release.v9"
    (broken / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="contract"):
        create_app(None, load_profiles(), Settings(estimator="model", model_dir=str(broken)))


def test_a_phone_streaming_to_the_model_gets_detections_on_the_room_state(model_bundle):
    app = create_app(
        None, load_profiles(), Settings(estimator="model", model_dir=str(model_bundle))
    )
    pcm = bundle_signal(seconds=2.0, gap_len=0)
    with TestClient(app) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello(profile="noe")))
        assert ws.receive_json()["type"] == "ready"
        for seq, offset in enumerate(range(0, len(pcm), 4800)):
            ws.send_bytes(packet(seq, pcm[offset : offset + 4800]))
        ws.send_text(json.dumps({"type": "ping", "t": 1}))
        while ws.receive_json()["type"] != "pong":
            pass
        with client.websocket_connect("/ws/state") as state_ws:
            state = state_ws.receive_json()
    [noe] = [p for p in state["phones"] if p["profile"] == "noe"]
    assert state["estimator"] == "model"
    assert noe["detection"] is not None


def test_the_release_folder_must_hold_the_announced_release(model_bundle, tmp_path):
    snapshot = tmp_path / "snapshot"
    shutil.copytree(model_bundle, snapshot / "edth.audio.24k-1s.r1")
    settings = Settings(
        estimator="model", model_repo="team/model", model_revision=SHA,
        model_release="edth.audio.24k-1s.r1",
    )
    with pytest.raises(ValueError, match="test.48k-w100.r0"):
        make_estimation(settings, load_profiles(), fetch=lambda *args: snapshot)
