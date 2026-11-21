import json

from fastapi.testclient import TestClient

from api.main import create_app
from conftest import make_hello


def test_serves_built_front_and_keeps_websocket(tmp_path):
    (tmp_path / "index.html").write_text("<title>Crozidrone · captation</title>")
    client = TestClient(create_app(front_dir=tmp_path))

    page = client.get("/")
    assert page.status_code == 200
    assert "Crozidrone · captation" in page.text

    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps(make_hello()))
        assert ws.receive_json()["type"] == "ready"


def test_without_front_dir_only_websocket_is_exposed():
    client = TestClient(create_app(front_dir=None))
    assert client.get("/").status_code == 404
