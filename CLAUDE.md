# Crozidrone — captation audio temps réel (EDTH Paris 2026)

Chaîne : téléphone (navigateur) → micro via le module partagé → WebSocket binaire → FastAPI.
Périmètre actuel : captation + logs de preuve uniquement (pas de modèle, fenêtrage, dashboard).

## Invariants non négociables (contrat audio)
- `vendor/edth/audio_capture.js` est **intouchable** (test SHA-256 dans `packages/audio-capture/tests/test_shared_module.py`).
  Le front importe `createPcmCapture`, `getCaptureSupport`, `CAPTURE_CONTRACT`, `WEBKIT_CAPTURE_CONTRACT`
  via l'alias `@edth/capture`. Ne jamais réimplémenter capture, contraintes micro ou quantification.
- Signal : mono, 48 000 Hz, PCM s16le, canal 0, octets exactement tels que fournis par `onChunk`.
  Interdits : rééchantillonnage, gain, normalisation, filtrage, codec avec perte (MediaRecorder,
  Opus, WebRTC média), conversion float côté client, contrainte `getUserMedia` supplémentaire.
- Contrat : celui choisi par le module (`captureSettings.capture_contract`), envoyé tel quel ;
  le serveur refuse tout contrat inconnu ; avertissement affiché pour le profil WebKit.
- Aucun calcul dans l'AudioWorklet (géré par le module).
- `onError` du module : jamais masqué, termine la session, log explicite, aucun repli.
- Niveau/RMS/crête : diagnostic seulement, ne modifient jamais les octets envoyés ou stockés.
- 1 capture = 1 session (UUID) = 1 WebSocket = flux continu. Jamais de recollage entre sessions.

Contrat de capture : `docs/audio-capture-contract.md`. Protocole : `docs/protocol.md`.

## Commandes
```bash
# serveur
# Python (workspace uv, tout depuis la racine)
uv sync --all-packages && uv run ruff check && uv run pytest
SAVE_SESSIONS=1 uv run uvicorn api.main:app --port 8000     # écrit ./recordings/
# front (HTTPS fourni par ngrok / Tailscale Serve devant le port Vite)
cd web && npm install && npm test && npm run build
cd web && npm run dev
# image de prod (Coolify)
docker build -t crozidrone . && docker run --rm -p 8000:8000 crozidrone
# e2e (lance uvicorn + vite, Chromium faux micro 440 Hz), depuis la racine
uv run --no-project --with playwright --with pytest --with numpy pytest e2e -q
```

## Repères
Arborescence : un package Python par module, assemblés par `services/api`.
```
packages/audio-capture/   ① récupération du son : protocol.py (validation à la frontière),
                             session.py (seq + SHA), stats.py (diagnostic), recording.py
services/api/             main.py (endpoint /ws/audio, create_app, logs `event=… clé=valeur`), logfmt.py,
                             profiles.py (charge et valide contracts/profiles.json au démarrage)
contracts/profiles.json   seule source des téléphones (id, libellé, position en mètres) pour Python et TS
web/src/capture/          ① page téléphone : packetizer.ts, streamer.ts (session, relance, reconnexion),
                             wakelock.ts (écran allumé), App.tsx (UI)
web/src/shared/           edth-capture.d.ts (types du module partagé), profiles.ts (contrat, alias `@contracts`)
conftest.py               helpers de test partagés (make_hello, sine, packet, TEAM_PROFILES lu du contrat)
```
À venir (ne pas créer avant d'en avoir le code) : `packages/features` (prétraitement commun
entraînement ↔ inférence), `packages/distance-estimation` (② son → distance),
`packages/localization` (③ distances → position), `packages/bus`, `ml/`,
`web/src/display/` (④ affichage des sources sonores + position du drone).
Règle : un module n'importe jamais un autre module ; seul `services/api` les assemble.

- Lot 2 fait : `network_too_slow`, reconnexion avec délai croissant (`docs/protocol.md`), Wake Lock.

## Qualité
`~/tools/crapper/crapper`, `~/tools/dryer/dryer`, `~/tools/mutator/mutator` (composants UI purs
exclus : `App.tsx`, `main.tsx`). `vendor/` est ignoré par ces outils.
- Python (depuis la racine) : `coverage run --source=packages,services -m pytest` puis
  `coverage lcov -o target/coverage/python/lcov.info`, avant
  `crapper --use-existing-coverage packages services`.
- TS : `npm run coverage` puis `crapper --use-existing-coverage src/<fichier>.ts` ;
  mutator : `--test-command "npx vitest run"`.
