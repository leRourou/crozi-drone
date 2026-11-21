# THC — captation audio temps réel (EDTH Paris 2026)

Téléphone (navigateur) → micro via le module partagé EDTH → WebSocket binaire → FastAPI.
Le serveur prouve en direct qu'il reçoit le son : statistiques chaque seconde et, à l'arrêt,
comparaison du SHA-256 du PCM entre téléphone et serveur (`match=✅`).

- Contrat audio : [docs/audio-capture-contract.md](docs/audio-capture-contract.md)
- Protocole : [docs/protocol.md](docs/protocol.md)
- Invariants et commandes pour les agents : [CLAUDE.md](CLAUDE.md)

## Prérequis
Node ≥ 20, [uv](https://docs.astral.sh/uv/), Python ≥ 3.11 (installé par uv si besoin).

## Lancer en local
```bash
cd server && uv sync && SAVE_SESSIONS=1 uv run uvicorn app.main:app --port 8000
# autre terminal
cd front && npm install && npm run dev        # http://localhost:5173
```
Ouvrir http://localhost:5173 dans Chrome (localhost = contexte sécurisé, micro autorisé),
cliquer **Démarrer**. Les logs du serveur ressemblent à :
```
INFO    event=session_start sid=ac031ed5 contract=edth.web-pcm.v1 browser="Chrome/159 Linux" mic="…" input_channels=2 ec=false ns=false agc=false
INFO    event=stats sid=ac031ed5 pps=20.00 audio_s=4.75 rt=0.95 kbps=768.66 peak_dbfs=-6.02 rms_dbfs=-9.03 max_gap_ms=85.28 gaps=0
INFO    event=session_end sid=ac031ed5 duration_s=5.58 frames=247168 client_frames=247168 server_sha=808fd5c3987cc8ae client_sha=808fd5c3987cc8ae match=✅ reason=manual
```
Avec `SAVE_SESSIONS=1`, chaque session est écrite dans `recordings/<session_id>.wav`
(octets reçus tels quels) pour réécoute.

## Tester sur un téléphone
Le micro exige HTTPS. On expose **le port Vite** (le proxy `/ws` relaie vers FastAPI : une seule
origine, `wss://` automatique).

**ngrok**
```bash
ngrok http 5173
```
Ouvrir l'URL `https://….ngrok-free.app` sur le téléphone (passer l'écran d'avertissement ngrok).

**Tailscale Serve** (téléphone sur le même tailnet)
```bash
tailscale serve --bg 5173
```
Ouvrir `https://<machine>.<tailnet>.ts.net`.

Autre domaine de tunnel : `THC_ALLOWED_HOSTS=mon.domaine.example npm run dev`.

Sur le téléphone : Chrome (Android) ou Safari (iOS) à jour, micro intégré (pas de Bluetooth),
écran allumé et onglet au premier plan pendant toute la capture. Vérifier dans le panneau de logs :
`micro ok … contract=…`, `ready`, des lignes `stats … rt≈1.00 kbps≈768`, puis après **Arrêter**
`end_ack … match=✅`.

## Tests
```bash
cd server && uv run ruff check && uv run pytest          # 72 tests
cd front && npm test && npm run build                    # 34 tests
# E2E Chromium (faux micro 440 Hz), depuis la racine :
uv run --no-project --with playwright python -m playwright install chromium   # une fois
uv run --no-project --with playwright --with pytest --with numpy pytest e2e -q
```

## Limites connues
- **Relance de session toutes les ~175 s** : le module garde toute la prise en mémoire et s'arrête
  à 16 Mio. Une nouvelle capture/session démarre automatiquement ; le trou est assumé et loggé
  (`gap_ms`). Disparaîtra avec l'option `retain: false` prévue dans le dépôt du collecteur.
  La relance hors geste utilisateur fonctionne sous Chromium (activation persistante de la page) ;
  non vérifié sous Safari.
- **Aucun vrai téléphone n'a été validé** à ce jour : seuls les tests automatisés (Chromium avec
  faux micro) ont été exécutés. **iPhone non testé** sur un appareil réel.
- **Traitements audio du système non certifiables** (`system_processing: "unverified"`) : le
  navigateur rapporte EC/NS/AGC désactivés, pas l'OS ni le matériel.
- Écran verrouillé, onglet en arrière-plan ou appel entrant : le module lève `audio-interrupted`,
  la session se termine (log explicite) ; relance manuelle.
- Pas encore de gestion réseau lent (`network_too_slow`), de reconnexion automatique ni de
  Wake Lock (lot 2) : `ws.bufferedAmount` est seulement affiché.
