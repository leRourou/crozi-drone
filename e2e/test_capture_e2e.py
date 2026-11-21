"""E2E Chromium : faux micro (WAV 440 Hz) → module partagé → WebSocket → FastAPI.

Lancement (depuis la racine) :
    uv run --no-project --with playwright --with pytest --with numpy pytest e2e -q
Prérequis : `cd web && npm install`, `uv sync --all-packages`, navigateur Playwright installé.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RATE = 48_000
TONE_HZ = 440.0
CAPTURE_SECONDS = 5


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310 - localhost uniquement
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(url)


def write_tone(path: Path, seconds: float = 30.0) -> None:
    t = np.arange(int(seconds * RATE)) / RATE
    pcm = np.round(0.5 * 32767 * np.sin(2 * np.pi * TONE_HZ * t)).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm.tobytes())


def dominant_frequency(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, RATE)
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float)
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / RATE)[np.argmax(spectrum)])


@pytest.fixture
def stack(tmp_path):
    api_port, web_port = free_port(), free_port()
    recordings = tmp_path / "recordings"
    env_api = {
        "SAVE_SESSIONS": "1",
        "RECORDINGS_DIR": str(recordings),
        "DISTANCE_ESTIMATOR": "scripted",
        "PATH": os.environ["PATH"],
    }
    env_web = {"CROZIDRONE_BACKEND": f"http://127.0.0.1:{api_port}", "PATH": os.environ["PATH"]}
    api_log = (tmp_path / "server.log").open("w")
    api = subprocess.Popen(
        ["uv", "run", "uvicorn", "api.main:app", "--port", str(api_port)],
        cwd=ROOT,
        env=env_api,
        stdout=api_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    web = subprocess.Popen(
        ["npx", "vite", "--port", str(web_port), "--strictPort", "--host", "127.0.0.1"],
        cwd=ROOT / "web",
        env=env_web,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        wait_http(f"http://127.0.0.1:{api_port}/docs")
        wait_http(f"http://127.0.0.1:{web_port}/")
        yield {
            "url": f"http://localhost:{web_port}/",
            "recordings": recordings,
            "server_log": tmp_path / "server.log",
        }
    finally:
        for proc in (web, api):
            # Tout le groupe : `npx` / `uv run` lancent vite / uvicorn comme processus enfants.
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        api_log.close()


def launch_with_fake_mic(pw, tmp_path):
    tone = tmp_path / "tone440.wav"
    write_tone(tone)
    return pw.chromium.launch(
        args=[
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            f"--use-file-for-fake-audio-capture={tone}",
            "--autoplay-policy=no-user-gesture-required",
        ]
    )


def start_capture(page, url, label):
    page.goto(url)
    page.get_by_label("Téléphone", exact=True).select_option(label=label)
    page.get_by_role("button", name="Continuer").click()
    page.get_by_role("button", name="Démarrer").click()


def test_the_state_page_shows_the_capturing_phone_and_its_simulated_distance(stack, tmp_path):
    with sync_playwright() as pw:
        browser = launch_with_fake_mic(pw, tmp_path)
        display = browser.new_page()
        display.goto(stack["url"] + "display.html")
        noe = display.locator('[data-profile="noe"]')
        noe.and_(display.locator('[data-status="never_seen"]')).wait_for(timeout=10_000)
        display.get_by_text("Estimateur simulé").wait_for()

        phone = browser.new_page()
        start_capture(phone, stack["url"], "Téléphone de Noé")
        noe.and_(display.locator('[data-status="streaming"]')).wait_for(timeout=15_000)
        detection = noe.locator(".detection")
        detection.filter(has_text=re.compile("Drone à|Aucun drone")).wait_for(timeout=5_000)
        statuses = display.locator(".phone").evaluate_all("els => els.map(e => e.dataset.status)")
        browser.close()

    assert statuses == ["streaming", "never_seen", "never_seen"], statuses


def test_fake_microphone_reaches_the_server_bit_exact(stack, tmp_path):
    with sync_playwright() as pw:
        browser = launch_with_fake_mic(pw, tmp_path)
        page = browser.new_page()
        page.goto(stack["url"])
        page.get_by_text("Détails").click()  # journal replié par défaut
        # Étape 1 : pas de bouton d'enregistrement tant que le profil n'est pas confirmé.
        proceed = page.get_by_role("button", name="Continuer")
        assert proceed.is_disabled()
        assert page.get_by_role("button", name="Démarrer").count() == 0
        page.get_by_label("Téléphone", exact=True).select_option(label="Téléphone de Noé")
        proceed.click()
        # Étape 2
        page.get_by_text("Étape 2 sur 2").wait_for()
        page.get_by_role("button", name="Démarrer").click()
        page.get_by_text("ready session=").wait_for(timeout=15_000)
        page.wait_for_timeout(CAPTURE_SECONDS * 1000)
        page.get_by_role("button", name="Arrêter").click()
        page.get_by_text("end_ack").wait_for(timeout=15_000)
        logs = page.locator(".logs li").all_inner_texts()[::-1]  # DOM : plus récent d'abord
        browser.close()

    text = "\n".join(logs)
    server_log = stack["server_log"].read_text()
    print(text, server_log, sep="\n--- server ---\n")
    assert "end_ack" in text and "match=✅" in text, text
    assert "match=✅" in server_log
    assert "ready session=" in text and "profile=noe" in text, text
    assert "profil renvoyé" not in text, text
    assert "profile=noe" in server_log

    ratios = [float(r) for r in re.findall(r"\bstats .*?rt=([0-9.]+)", text)]
    assert ratios, "aucun message stats reçu"
    assert 0.9 <= ratios[-1] <= 1.1, ratios

    [recording] = list(stack["recordings"].glob("noe_*.wav"))
    assert dominant_frequency(recording) == pytest.approx(TONE_HZ, abs=2.0)
