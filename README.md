# Crozidrone

**English** | [Français](README.fr.md)

Acoustic drone detection and localization using the microphones of several smartphones.
Built during EDTH Paris 2026.

Each phone streams its microphone audio to a server in real time. For each phone, a model estimates
whether a drone is audible and how far away it is. The distances are then fused through
multilateration and a Kalman filter to place the drone on a map of the room.

```
 Phones (browser)                 FastAPI server                                Monitoring PC
┌──────────────────────┐   PCM   ┌────────────────────────────────────────┐    ┌──────────────────┐
│ ① mic capture        │ ──────► │ ① ingestion    ② range     ③ position │ ─► │ ④ room map       │
│   48 kHz mono s16le  │   WS    │   /ws/audio      (model)     (EKF)     │ WS │   2D / 3D        │
└──────────────────────┘         └────────────────────────────────────────┘    └──────────────────┘
                                                                  /ws/state
```

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Known limitations](#known-limitations)
- [Models and data](#models-and-data)
- [Team](#team)

## How it works

| Stage | Code | Role |
| --- | --- | --- |
| ① Capture | `packages/audio-capture`, `web/src/capture` | Phone page; raw PCM stream over WebSocket, validated on arrival (format, continuity, SHA-256) |
| ② Range estimation | `packages/distance-estimation` | Drone presence and distance over 100 ms sliding windows; real model or simulated drone |
| ③ Localization | `packages/localization`, `services/api/.../fusion.py` | Multilateration from at least 3 distances, then tracking with an extended Kalman filter |
| ④ Display | `web/src/display` | Room map: phone status, range circles, drone position and track |

**Audio contract.** Capture goes exclusively through the module shared with the data collection
team (`vendor/edth/audio_capture.js`), so that the server receives exactly the same bytes the model
was trained on: mono, 48 kHz, 16-bit PCM, with no resampling, gain, filtering or lossy codec. This
file must not be modified; a test checks its hash.
See [docs/audio-capture-contract.md](docs/audio-capture-contract.md) (French).

**Model.** The server loads a release published by the ML team (`edth.audio.48k-w100.r1`, MLPs for
detection and range), either from a local directory or from a Hugging Face repository pinned to a
commit. At startup it checks the manifest, compares the frozen inference code (`packages/features`)
and replays a parity test set; on any mismatch it refuses to start instead of falling back to a mock.

**Real time only.** No history is stored and no session is replayed. WAV recording
(`SAVE_SESSIONS=1`) exists only as evidence and is disabled by default.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/) ≥ 0.9
- Node.js 24 and npm
- An HTTPS tunnel (ngrok, Tailscale Serve…) for the phones: browsers only grant microphone access
  on a secure origin
- On the phones, a recent Chromium-based browser (the capture contract's reference); Firefox may
  work but must be checked, iPhone / Safari is not validated

## Quick start

```bash
# 1. Dependencies
uv sync --all-packages
(cd web && npm install)

# 2. Server, with the simulated drone to see the whole pipeline without a real drone
DISTANCE_ESTIMATOR=scripted uv run uvicorn api.main:app --port 8000

# 3. Front end (second terminal): Vite on port 5173, proxying /ws to the server
cd web && npm run dev

# 4. Expose Vite over HTTPS for the phones
ngrok http 5173            # or: tailscale serve 5173
```

Then:

- **On each phone**: open the HTTPS URL, pick the phone from the list, start.
- **On the monitoring PC**: open `/display.html` (in production, `/display` redirects to it).

Phones and their position in the room are declared in
[`contracts/profiles.json`](contracts/profiles.json), the single source shared by server and front end.

### With the real model

```bash
cp .env.example .env
# Uncomment DISTANCE_ESTIMATOR=model and the DISTANCE_MODEL_* variables, set HF_TOKEN if needed
uv run uvicorn api.main:app --port 8000 --env-file .env
```

The first start downloads the release into the Hugging Face cache. To do it ahead of time
(at deploy time, for instance): `uv run --env-file .env python -m api.model_fetch`.

## Configuration

The server is configured through environment variables only. All of them are optional, except the
model variables when `DISTANCE_ESTIMATOR=model`. They are validated at startup: an invalid value
stops the server with an error naming the variable.

| Variable | Default | Role |
| --- | --- | --- |
| `DISTANCE_ESTIMATOR` | `none` | `none`, `scripted` (simulated drone) or `model` |
| `DISTANCE_MODEL_DIR` | — | Local release bundle; takes precedence over Hugging Face |
| `DISTANCE_MODEL_REPO` / `_REVISION` / `_RELEASE` | — | HF repository, pinned commit sha, release folder |
| `HF_TOKEN` | — | Hugging Face token (never logged) |
| `MODEL_PERIOD_MS` | `100` | Model estimation interval |
| `SAVE_SESSIONS` | — | `1` to write each session as WAV into `RECORDINGS_DIR` (`./recordings`) |

The full list (real-time settings, drone track, simulated drone) is commented in
[`.env.example`](.env.example) and detailed in [docs/protocol.md](docs/protocol.md) (French).

The Vite dev server reads two shell variables: `CROZIDRONE_BACKEND` (`/ws` proxy target,
`http://127.0.0.1:8000` by default) and `CROZIDRONE_ALLOWED_HOSTS` (extra tunnel hosts,
comma-separated; ngrok and `*.ts.net` are already allowed).

## Repository layout

uv workspace: one Python package per stage, wired together by a single service. A package never
imports another package; only `services/api` connects them.

```
packages/
  audio-capture/          ① protocol, sessions, ingestion statistics, WAV recording
  distance-estimation/    ② estimator interface, release loading, live path, mock
  localization/           ③ multilateration (localiser_drone) and EKF tracking (SuiviDrone)
  features/               frozen copy of the ML release's inference code (do not edit)
services/api/             FastAPI app: /ws/audio, /ws/state, fusion, settings
web/
  src/capture/            phone page
  src/display/            2D room map, lazily loaded 3D view (three.js)
  src/shared/             shared module types, profiles, network helpers
contracts/profiles.json   phones and positions (x, y, z in metres)
vendor/edth/              shared capture module (read-only)
docs/                     WebSocket protocol and capture contract
e2e/                      end-to-end test (Chromium with a fake microphone)
```

## Testing

```bash
# Python: lint + unit tests
uv run ruff check && uv run pytest

# Front end: tests, type check and build
cd web && npm test && npm run build

# End to end: starts uvicorn and Vite, Chromium with a fake 440 Hz microphone
uv run --no-project --with playwright --with pytest --with numpy pytest e2e -q
```

The e2e test needs a Playwright browser (`uv run --with playwright playwright install chromium`).

Some tests guard project invariants and must not be bypassed: SHA-256 hashes of the shared capture
module and of the frozen `packages/features` copy, model parity replayed at load time.

## Deployment

A single image serves the built front end, the WebSockets and the API on one port; HTTPS is expected
upstream (reverse proxy).

```bash
docker build -t crozidrone .
docker run --rm -p 8000:8000 --env-file .env -v crozidrone-data:/data crozidrone
```

The `/data` volume holds recordings and the Hugging Face cache, so the model is not downloaded again
on every restart. The image is deployed on Coolify, whose proxy terminates HTTPS.

## Documentation

The detailed documentation is written in French.

- [WebSocket protocol](docs/protocol.md): `/ws/audio` and `/ws/state` messages, validation, model
  loading, localization output, every environment variable
- [Capture contract](docs/audio-capture-contract.md): signal parameters, WebKit profile, training
  data provenance
- [Frozen code provenance](packages/features/PROVENANCE.md): release, hashes, update procedure

## Known limitations

- iPhone / Safari: the WebKit capture profile is accepted but has not been validated.
- Distances predicted by release r1 are clamped to [1, 5] m.
- With all phones at the same height, distances alone barely constrain altitude; the track is pulled
  towards `TRACK_ALTITUDE_M`.

## Models and data

The trained models and the dataset are published on Hugging Face:

- Models: [ImAPancake/EDTH_Paris26_models](https://huggingface.co/ImAPancake/EDTH_Paris26_models)
- Dataset: [ImAPancake/EDTH_Paris26_dataset](https://huggingface.co/datasets/ImAPancake/EDTH_Paris26_dataset)

## Team

| Member | Contributions |
| --- | --- |
| Tristan ([@XXGIGASHADOWPAUL38XX](https://github.com/XXGIGASHADOWPAUL38XX)) | Audio pre-processing and signal processing, feature extraction, data formatting, benchmarking |
| Noé ([@NoeGuedet](https://github.com/NoeGuedet)) | Dataset design and collection, model training, benchmarking |
| Axel ([@leRourou](https://github.com/leRourou)) | Architecture, web application, design, deployment |
| Maxence ([@m-cheve](https://github.com/m-cheve)) | Drone localization from range data, Kalman filter |
| Charlène ([@Charlene7508](https://github.com/Charlene7508)) | Product vision, project management, organization and communication |
