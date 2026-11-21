# THC — captation audio temps réel (EDTH Paris 2026)

Chaîne : téléphone (navigateur) → micro via le module partagé → WebSocket binaire → FastAPI.
Périmètre actuel : captation + logs de preuve uniquement (pas de modèle, fenêtrage, dashboard).

## Invariants non négociables (contrat audio)
- `vendor/edth/audio_capture.js` est **intouchable** (test SHA-256 dans `server/tests/test_shared_module.py`).
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
cd server && uv sync && uv run ruff check && uv run pytest
cd server && SAVE_SESSIONS=1 uv run uvicorn app.main:app --port 8000   # écrit recordings/
# front (HTTPS fourni par ngrok / Tailscale Serve devant le port Vite)
cd front && npm install && npm test && npm run build
cd front && npm run dev
# e2e (lance uvicorn + vite, Chromium faux micro 440 Hz), depuis la racine
uv run --no-project --with playwright --with pytest --with numpy pytest e2e -q
```

## Repères
- Serveur : `server/app/protocol.py` (validation à la frontière), `session.py` (seq + SHA),
  `stats.py` (diagnostic), `main.py` (endpoint, logs `event=… clé=valeur`).
- Front : `front/src/packetizer.ts`, `streamer.ts` (session, relance après limite), `App.tsx` (UI).
- Lot 2 non fait : `network_too_slow`, reconnexion avec délai croissant, Wake Lock.

## Qualité
`~/tools/crapper/crapper`, `~/tools/dryer/dryer`, `~/tools/mutator/mutator` (composants UI purs
exclus : `App.tsx`, `main.tsx`). `vendor/` est ignoré par ces outils.
- Python : générer `server/target/coverage/python/lcov.info` (`coverage run -m pytest` puis
  `coverage lcov`) avant `crapper --use-existing-coverage app`.
- TS : `npm run coverage` puis `crapper --use-existing-coverage src/<fichier>.ts` ;
  mutator : `--test-command "npx vitest run"`.
