"""Cycle de vie d'une connexion, piloté avec une fausse WebSocket et une période de stats courte."""

import asyncio
import json
import logging

import pytest

from api import main
from api.main import Connection
from conftest import TEAM_PROFILES, make_hello, packet


class FakeWebSocket:
    def __init__(self, messages):
        self.incoming = asyncio.Queue()
        for message in messages:
            self.incoming.put_nowait(message)
        self.sent = []
        self.closed = 0

    async def accept(self):
        pass

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, data):
        if self.closed:
            raise RuntimeError("send after close")
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed += 1


def text(obj):
    return {"type": "websocket.receive", "text": json.dumps(obj)}


def binary(data):
    return {"type": "websocket.receive", "bytes": data}


DISCONNECT = {"type": "websocket.disconnect", "code": 1001}
END = {"type": "end", "reason": "manual", "frames": 0, "pcm_sha256": None}


@pytest.fixture(autouse=True)
def fast_stats(monkeypatch):
    monkeypatch.setattr(main, "STATS_PERIOD_S", 0.02)


def run(ws, settle=0.1):
    async def scenario():
        await asyncio.wait_for(Connection(ws, TEAM_PROFILES).run(), timeout=1.0)
        await asyncio.sleep(settle)  # laisse une éventuelle boucle fantôme se manifester

    asyncio.run(scenario())
    return [m["type"] for m in ws.sent]


def test_session_continues_after_ping():
    ws = FakeWebSocket(
        [text(make_hello()), text({"type": "ping", "t": 1}), binary(packet(0, [1])), text(END)]
    )
    types = run(ws)
    assert types[:2] == ["ready", "pong"]
    assert types[-1] == "end_ack"


def test_end_terminates_the_session_once(caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    ws = FakeWebSocket([text(make_hello()), text(END), DISCONNECT])
    run(ws)
    assert ws.closed == 1
    assert caplog.text.count("event=session_end") == 1


def test_disconnect_terminates_the_session(caplog):
    caplog.set_level(logging.INFO, logger="crozidrone.audio")
    ws = FakeWebSocket([text(make_hello()), DISCONNECT])
    run(ws)
    assert caplog.text.count("event=session_end") == 1
    assert "event=stats" not in caplog.text.split("event=session_end")[1]


def test_stats_are_sent_while_idle():
    ws = FakeWebSocket([text(make_hello())])

    async def scenario():
        task = asyncio.create_task(Connection(ws, TEAM_PROFILES).run())
        await asyncio.sleep(0.07)
        await ws.incoming.put(DISCONNECT)
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(scenario())
    assert [m["type"] for m in ws.sent].count("stats") >= 2


def test_disconnect_before_hello_is_silent():
    ws = FakeWebSocket([DISCONNECT])
    assert run(ws) == []
