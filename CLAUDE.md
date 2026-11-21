# Crozidrone — captation audio temps réel (EDTH Paris 2026)

Chaîne : téléphone (navigateur) → micro via le module partagé → WebSocket binaire → FastAPI.
Périmètre actuel : captation + logs de preuve, état général des téléphones (`/ws/state`, page `display.html`),
② simulé (trajectoire scriptée) ou vrai modèle (release du repo ML), ③ branché (`fusion.py`) ; la page d'état est le plan
de la salle de démo (téléphones, cercles de distance, drone).
Hors périmètre : iPhone / Safari. Le profil WebKit reste accepté tel quel (module partagé) mais n'est pas validé.

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
DISTANCE_ESTIMATOR=scripted uv run uvicorn api.main:app --port 8000  # drone virtuel (défaut : none)
# vrai modèle : release HF épinglée (HF_TOKEN dans l'environnement), ou DISTANCE_MODEL_DIR=<bundle local>
DISTANCE_ESTIMATOR=model DISTANCE_MODEL_REPO=ImAPancake/EDTH_ml_models \
  DISTANCE_MODEL_REVISION=e7a6a5444bb72f08ee9c7dfea00fe78e5a9fbee7 \
  DISTANCE_MODEL_RELEASE=edth.audio.48k-w100.r1 uv run uvicorn api.main:app --port 8000
# MODEL_PERIOD_MS=100 (cadence des estimations, multiple du pas de la release) MODEL_UNCERTAINTY=0.10
uv run python -m api.model_fetch   # mêmes variables : tire la release dans le cache HF (déploiement)
# réglages temps réel (ms) : DISTANCE_WINDOW_MS=250 STATE_PERIOD_MS=250 STALE_AFTER_MS=1000
# DETECTION_FRESH_MS=2000 — lus et validés par services/api/settings.py (docs/protocol.md)
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
packages/distance-estimation/ ② son → distance : estimator.py (interface AudioWindow → DistanceEstimate,
                             range None = pas de drone), windows.py (fenêtres contiguës d'une session),
                             scripted.py (mock : drone virtuel sur un cercle, vraie distance),
                             release.py (bundle edth.model-release.v2 : manifeste, code figé, colonnes,
                             recette features.recompute, parité rejouée au chargement), stream.py (chemin
                             live : décimation continue, fenêtres glissantes, QC zéros sur le 48 kHz),
                             model.py (ModelEstimator : une estimation par période MODEL_PERIOD_MS)
packages/features/        copie figée de dsp.py / features.py / ml.py de la release (modules top-level
                             `dsp`, `features`, `ml` : les pickles référencent `ml`) ; test SHA-256,
                             PROVENANCE.md ; torch CPU gardé (inutile à la r1 en MLP, prêt pour un CNN)
services/api/             main.py (/ws/audio, /ws/state, create_app, make_estimation, logs `event=… clé=valeur`),
                             settings.py (seul lecteur des variables d'environnement du temps réel),
                             state.py (PhoneRegistry : état par téléphone, la session la plus récente gagne),
                             fusion.py (③ : sélection des détections, localiser_drone en thread, piste `Tracker`, tâche de fond),
                             model_fetch.py (bundle du modèle : DISTANCE_MODEL_DIR ou snapshot HF épinglé),
                             logfmt.py, profiles.py (charge et valide contracts/profiles.json au démarrage)
contracts/profiles.json   seule source des téléphones (id, libellé, position x ; y ; z en mètres) pour Python et TS
web/src/capture/          ① page téléphone : packetizer.ts, streamer.ts (session, relance, reconnexion),
                             wakelock.ts (écran allumé), App.tsx (UI)
web/src/display/          ④ plan de salle (display.html ; /display redirige, en dev Vite taper /display.html) :
                             state.ts (message validé à l'arrivée), stateclient.ts (abonnement, reconnexion),
                             room.ts (plan de la salle en mètres), mapgeom.ts (cercles, écoute), format.ts,
                             MapView.tsx / Panel.tsx / icons.tsx / App.tsx (UI)
web/src/shared/           edth-capture.d.ts (types du module partagé), profiles.ts (contrat, alias `@contracts`),
                             net.ts (URL ws/wss, délai de reconnexion), theme.css (palette)
packages/localization/    ③ distances → position : calculation.py `localiser_drone` (capteurs 3D, `tol`
                             relative, grille ≈ 60 ms/appel, appelé dans un thread). Code de Maxence,
                             fins de ligne CRLF conservées.
                             tracking.py `SuiviDrone` : EKF sur les distances (piste `track`, lissage),
                             démarré sur la zone de `localiser_drone`, altitude tirée vers TRACK_ALTITUDE_M.
conftest.py               helpers de test partagés (make_hello, sine, packet, TEAM_PROFILES lu du contrat,
                             write_model_bundle : bundle de release de test au format r0)
```
À venir (ne pas créer avant d'en avoir le code) : `ml/`.
Règle : un module n'importe jamais un autre module ; seul `services/api` les assemble. `packages/features`
n'est pas un module ①–④ mais une bibliothèque figée (comme numpy), importée par distance-estimation.

- Lot 2 fait : `network_too_slow`, reconnexion avec délai croissant (`docs/protocol.md`), Wake Lock.
- Lot 3 fait : z = 0 dans le contrat, mock de ② (`DISTANCE_ESTIMATOR=scripted`), `/ws/state` + page d'état,
  `session_replaced`.
- Tout se fait en temps réel : pas de stockage d'historique ni de rejeu (décision du 21/11/2026).
  Les WAV `SAVE_SESSIONS=1` restent une option de preuve, désactivée par défaut.
- Lot 4 fait : drone simulé à l'échelle de la salle (`SCRIPTED_*`), ③ branché (`drone` dans `/ws/state`),
  plan de salle cliquable. Pas de `packages/bus` : ③ ne combine que des détections à ≤ `FUSION_SPREAD_MS`.
- Lot 5 fait : vrai modèle de ② (`DISTANCE_ESTIMATOR=model`) ; les mocks `none` / `scripted` restent.
  Contrat ML v2, release r1 (`edth.audio.48k-w100.r1`) validée de bout en bout ; la r0 (v1) n'est plus
  chargeable (une seule version du code figé à la fois). Nouvelle release : recopier son `frozen/` dans
  `packages/features` (+ empreintes du test et PROVENANCE.md) si le code change, puis changer
  `DISTANCE_MODEL_REVISION` / `DISTANCE_MODEL_RELEASE` ; le démarrage refuse toute incohérence.

## Qualité
`~/tools/crapper/crapper`, `~/tools/dryer/dryer`, `~/tools/mutator/mutator` (composants UI purs
exclus : `App.tsx`, `main.tsx`, `MapView.tsx`, `Panel.tsx`, `icons.tsx`). `vendor/` est ignoré par ces outils ;
la copie figée `packages/features/src` est exclue (ruff aussi) : ne pas la corriger.
- Python (depuis la racine) : `coverage run --source=packages,services -m pytest` puis
  `coverage lcov -o target/coverage/python/lcov.info`, avant
  `crapper --use-existing-coverage packages services`.
- TS : `npm run coverage` puis `crapper --use-existing-coverage src/<fichier>.ts` ;
  mutator : `--test-command "npx vitest run"`. La couverture V8 ne marque que la 1ʳᵉ ligne d'une expression
  sur plusieurs lignes : mutator les dit « non couvertes » ; les vérifier avec `--no-coverage --lines …`.
