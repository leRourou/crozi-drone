# Crozidrone

Détection et localisation acoustique d'un drone à partir des micros de plusieurs téléphones.
Projet réalisé pendant l'EDTH Paris 2026.

Chaque téléphone diffuse le son de son micro en temps réel vers un serveur. Un modèle estime, pour
chaque téléphone, si un drone est audible et à quelle distance il se trouve. Les distances sont
ensuite combinées par multilatération et un filtre de Kalman pour placer le drone sur le plan de la
salle.

```
 Téléphones (navigateur)          Serveur FastAPI                               PC de supervision
┌──────────────────────┐   PCM   ┌────────────────────────────────────────┐    ┌──────────────────┐
│ ① capture micro      │ ──────► │ ① réception    ② distance  ③ position │ ─► │ ④ plan de salle  │
│   48 kHz mono s16le  │   WS    │   /ws/audio      (modèle)    (EKF)     │ WS │   2D / 3D        │
└──────────────────────┘         └────────────────────────────────────────┘    └──────────────────┘
                                                                  /ws/state
```

## Sommaire

- [Fonctionnement](#fonctionnement)
- [Prérequis](#prérequis)
- [Démarrage rapide](#démarrage-rapide)
- [Configuration](#configuration)
- [Structure du dépôt](#structure-du-dépôt)
- [Tests et qualité](#tests-et-qualité)
- [Déploiement](#déploiement)
- [Documentation](#documentation)
- [Limites connues](#limites-connues)
- [Modèles et données](#modèles-et-données)
- [Équipe](#équipe)

## Fonctionnement

| Étape | Code | Rôle |
| --- | --- | --- |
| ① Captation | `packages/audio-capture`, `web/src/capture` | Page téléphone ; flux PCM brut par WebSocket, validé à l'arrivée (format, continuité, SHA-256) |
| ② Distance | `packages/distance-estimation` | Présence d'un drone et distance, par fenêtres glissantes de 100 ms ; vrai modèle ou drone simulé |
| ③ Localisation | `packages/localization`, `services/api/.../fusion.py` | Multilatération à partir d'au moins 3 distances, puis suivi par filtre de Kalman étendu |
| ④ Affichage | `web/src/display` | Plan de la salle : état des téléphones, cercles de distance, position et piste du drone |

**Contrat audio.** La capture passe exclusivement par le module partagé avec l'équipe de collecte
(`vendor/edth/audio_capture.js`), pour que le serveur reçoive exactement les mêmes octets que ceux sur
lesquels le modèle a été entraîné : mono, 48 kHz, PCM 16 bits, sans rééchantillonnage, gain, filtrage
ni codec avec perte. Ce fichier ne doit pas être modifié ; un test vérifie son empreinte.
Voir [docs/audio-capture-contract.md](docs/audio-capture-contract.md).

**Modèle.** Le serveur charge une release publiée par l'équipe ML (`edth.audio.48k-w100.r1`, MLP de
détection et de distance), depuis un dossier local ou un dépôt Hugging Face à révision épinglée. Au
démarrage, il vérifie le manifeste, compare le code d'inférence figé (`packages/features`) et rejoue
un lot de parité ; à la moindre incohérence, il refuse de démarrer plutôt que de basculer sur un mock.

**Temps réel uniquement.** Aucun historique n'est stocké et aucune session n'est rejouée.
L'enregistrement WAV (`SAVE_SESSIONS=1`) n'existe qu'à titre de preuve et est désactivé par défaut.

## Prérequis

- Python 3.12 et [uv](https://docs.astral.sh/uv/) ≥ 0.9
- Node.js 24 et npm
- Un tunnel HTTPS (ngrok, Tailscale Serve…) pour les téléphones : les navigateurs n'autorisent
  l'accès au micro que sur une origine sécurisée
- Côté téléphone, un navigateur Chromium récent (référence du contrat de capture) ; Firefox peut
  convenir mais doit être vérifié, iPhone / Safari n'est pas validé

## Démarrage rapide

```bash
# 1. Dépendances
uv sync --all-packages
(cd web && npm install)

# 2. Serveur, avec le drone simulé pour voir la chaîne complète sans drone réel
DISTANCE_ESTIMATOR=scripted uv run uvicorn api.main:app --port 8000

# 3. Front (autre terminal) : Vite sur le port 5173, qui relaie /ws vers le serveur
cd web && npm run dev

# 4. Exposer Vite en HTTPS pour les téléphones
ngrok http 5173            # ou : tailscale serve 5173
```

Ensuite :

- **Sur chaque téléphone** : ouvrir l'URL HTTPS, choisir son téléphone dans la liste, démarrer.
- **Sur le PC de supervision** : ouvrir `/display.html` (en production, `/display` redirige).

Les téléphones et leur position dans la salle sont déclarés dans
[`contracts/profiles.json`](contracts/profiles.json), seule source partagée par le serveur et le front.

### Avec le vrai modèle

```bash
cp .env.example .env
# Décommenter DISTANCE_ESTIMATOR=model et les variables DISTANCE_MODEL_*, renseigner HF_TOKEN si besoin
uv run uvicorn api.main:app --port 8000 --env-file .env
```

Le premier démarrage télécharge la release dans le cache Hugging Face. Pour le faire à l'avance
(au déploiement, par exemple) : `uv run --env-file .env python -m api.model_fetch`.

## Configuration

Le serveur se configure uniquement par variables d'environnement. Toutes sont facultatives sauf celles
du modèle quand `DISTANCE_ESTIMATOR=model`. Elles sont validées au démarrage : une valeur invalide
arrête le serveur avec un message qui nomme la variable.

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `DISTANCE_ESTIMATOR` | `none` | `none`, `scripted` (drone simulé) ou `model` |
| `DISTANCE_MODEL_DIR` | — | Bundle de release local ; prioritaire sur Hugging Face |
| `DISTANCE_MODEL_REPO` / `_REVISION` / `_RELEASE` | — | Dépôt HF, sha de commit épinglé, dossier de la release |
| `HF_TOKEN` | — | Jeton Hugging Face (jamais journalisé) |
| `MODEL_PERIOD_MS` | `100` | Cadence des estimations du modèle |
| `SAVE_SESSIONS` | — | `1` pour écrire chaque session en WAV dans `RECORDINGS_DIR` (`./recordings`) |

La liste complète (réglages temps réel, piste du drone, drone simulé) est commentée dans
[`.env.example`](.env.example) et détaillée dans [docs/protocol.md](docs/protocol.md).

Le serveur de dev Vite lit deux variables du shell : `CROZIDRONE_BACKEND` (cible du proxy `/ws`,
`http://127.0.0.1:8000` par défaut) et `CROZIDRONE_ALLOWED_HOSTS` (hôtes de tunnel supplémentaires,
séparés par des virgules ; ngrok et `*.ts.net` sont déjà autorisés).

## Structure du dépôt

Workspace uv : un package Python par étape, assemblés par un seul service. Un package n'importe
jamais un autre package ; seul `services/api` les relie.

```
packages/
  audio-capture/          ① protocole, sessions, statistiques de réception, enregistrement WAV
  distance-estimation/    ② interface d'estimation, chargement de release, chemin live, mock
  localization/           ③ multilatération (localiser_drone) et suivi EKF (SuiviDrone)
  features/               copie figée du code d'inférence de la release ML (ne pas modifier)
services/api/             application FastAPI : /ws/audio, /ws/state, fusion, réglages
web/
  src/capture/            page téléphone
  src/display/            plan de salle 2D, vue 3D (three.js) chargée à la demande
  src/shared/             types du module partagé, profils, utilitaires réseau
contracts/profiles.json   téléphones et positions (x, y, z en mètres)
vendor/edth/              module de capture partagé (intouchable)
docs/                     protocole WebSocket et contrat de capture
e2e/                      test de bout en bout (Chromium avec faux micro)
```

## Tests et qualité

```bash
# Python : lint + tests unitaires
uv run ruff check && uv run pytest

# Front : tests, vérification de types et build
cd web && npm test && npm run build

# Bout en bout : lance uvicorn et Vite, Chromium avec un faux micro à 440 Hz
uv run --no-project --with playwright --with pytest --with numpy pytest e2e -q
```

Le test e2e nécessite un navigateur Playwright (`uv run --with playwright playwright install chromium`).

Certains tests protègent des invariants du projet et ne doivent pas être contournés : empreinte
SHA-256 du module de capture partagé et de la copie figée `packages/features`, parité du modèle
rejouée au chargement.

## Déploiement

Une image unique sert le front buildé, les WebSockets et l'API sur le même port ; le HTTPS est
attendu en amont (reverse proxy).

```bash
docker build -t crozidrone .
docker run --rm -p 8000:8000 --env-file .env -v crozidrone-data:/data crozidrone
```

Le volume `/data` contient les enregistrements et le cache Hugging Face, ce qui évite de retélécharger
le modèle à chaque redémarrage. L'image est déployée sur Coolify, dont le proxy assure le HTTPS.

## Documentation

- [Protocole WebSocket](docs/protocol.md) : messages de `/ws/audio` et `/ws/state`, validation,
  chargement du modèle, sortie de la localisation, toutes les variables d'environnement
- [Contrat de capture](docs/audio-capture-contract.md) : paramètres du signal, profil WebKit,
  provenance des données d'entraînement
- [Provenance du code figé](packages/features/PROVENANCE.md) : release, empreintes, procédure de mise à jour

## Limites connues

- iPhone / Safari : le profil de capture WebKit est accepté mais n'a pas été validé.
- La distance prédite par la release r1 est bornée à [1, 5] m.
- Les téléphones étant posés au même niveau, les distances seules contraignent mal l'altitude ;
  la piste est ramenée vers `TRACK_ALTITUDE_M`.

## Modèles et données

Les modèles entraînés et le jeu de données sont publiés sur Hugging Face :

- Modèles : [ImAPancake/EDTH_Paris26_models](https://huggingface.co/ImAPancake/EDTH_Paris26_models)
- Dataset : [ImAPancake/EDTH_Paris26_dataset](https://huggingface.co/datasets/ImAPancake/EDTH_Paris26_dataset)

## Équipe

| Membre | Contributions |
| --- | --- |
| Tristan ([@XXGIGASHADOWPAUL38XX](https://github.com/XXGIGASHADOWPAUL38XX)) | Pré-traitement et traitement du son, extraction des features, mise en forme des données, benchmarking |
| Noé ([@NoeGuedet](https://github.com/NoeGuedet)) | Conception et constitution du dataset, entraînement des modèles, benchmarking |
| Axel ([@leRourou](https://github.com/leRourou)) | Architecture, application web, design, déploiement |
| Maxence ([@m-cheve](https://github.com/m-cheve)) | Localisation du drone à partir des distances, filtre de Kalman |
| Charlène ([@Charlene7508](https://github.com/Charlene7508)) | Vision produit, gestion de projet, organisation et communication |
