import json

from fastapi.testclient import TestClient

from api.main import create_app
from api.profiles import Profile, load_profiles
from conftest import make_hello


def test_serves_built_front_and_keeps_websocket(tmp_path):
    (tmp_path / "index.html").write_text("<title>Crozidrone · captation</title>")
    client = TestClient(create_app(front_dir=tmp_path, profiles=load_profiles()))

    page = client.get("/")
    assert page.status_code == 200
    assert "Crozidrone · captation" in page.text

    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello()))
        assert ws.receive_json()["type"] == "ready"


def test_without_front_dir_only_websocket_is_exposed():
    client = TestClient(create_app(front_dir=None, profiles=load_profiles()))
    assert client.get("/").status_code == 404


def test_the_websocket_accepts_exactly_the_profiles_given_to_the_app():
    zoe = Profile(id="zoe", label="Téléphone de Zoé", x_m=0.0, y_m=0.0, z_m=0.0)
    client = TestClient(create_app(front_dir=None, profiles=(zoe,)))
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello(profile="zoe")))
        assert ws.receive_json()["profile"] == "zoe"
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello(profile="tristan")))
        assert ws.receive_json()["code"] == "unknown_profile"


def test_display_redirects_to_the_state_page(tmp_path):
    (tmp_path / "index.html").write_text("captation")
    (tmp_path / "display.html").write_text("<title>Crozidrone · état</title>")
    client = TestClient(create_app(front_dir=tmp_path, profiles=load_profiles()))

    redirect = client.get("/display", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/display.html"
    assert "Crozidrone · état" in client.get("/display").text
