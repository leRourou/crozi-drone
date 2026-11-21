# Protocole WebSocket `crozidrone.audio-stream.v1`

Transport temps réel du PCM produit par le module partagé `vendor/edth/audio_capture.js`
(contrats `edth.web-pcm.v1` / `edth.web-pcm.webkit.v1`, voir `audio-capture-contract.md`).

- **Endpoint** : `/ws/audio` (servi par FastAPI ; en dev, Vite le relaie via son proxy `/ws`,
  donc une seule origine HTTPS et `wss://` déduit de `location`).
- **Règle** : 1 capture = 1 session = 1 connexion WebSocket = un flux continu d'échantillons.
  Toute discontinuité (reconnexion, relance après la limite du module, erreur) ouvre une nouvelle
  capture avec un nouvel UUID. Les échantillons de deux sessions ne sont jamais recollés.

## Client → serveur

### `hello` (texte, premier message obligatoire)
```json
{ "type": "hello", "protocol": "crozidrone.audio-stream.v1", "session_id": "<uuid v4>",
  "profile": "noe|tristan|maxence",
  "capture_settings": { "…": "captureSettings renvoyé par start(), intégral" },
  "captured_at": "<ISO UTC>", "user_agent": "…" }
```

`profile` : téléphone de l'équipe choisi sur la page avant d'enregistrer (obligatoire, non mémorisé).
Identifiants ASCII stables (`[a-z0-9_]+`). **Référence unique : `contracts/profiles.json`**
(identifiant, libellé affiché, position du téléphone `position_m` en mètres, repère local x ; y ; z,
z = hauteur, 0 pour les téléphones posés au sol).
Le front l'importe au build (`web/src/shared/profiles.ts`) ; `services/api` le valide au démarrage
(chemin modifiable par `PROFILES_FILE`) et transmet les identifiants à `parse_hello`. Une relance après
la limite du module garde le profil.

### Paquets audio (binaire)
`[seq : uint32 LE][échantillons Int16 LE]`

- `seq` commence à 0 et augmente de 1 par paquet.
- 2 400 échantillons par paquet (50 ms à 48 kHz) ; seul le dernier paquet d'une session peut être
  plus court (vidage à l'arrêt).
- Les blocs de 128 échantillons de `onChunk` sont concaténés puis redécoupés sans modification.
- Le client refuse de démarrer sur une plateforme big-endian.

### `ping` (texte, toutes les 2 s)
`{"type":"ping","t":<performance.now()>}` — le serveur renvoie `t` tel quel (aller-retour).

### `end` (texte, à l'arrêt)
`{"type":"end","reason":"manual|limit|network_too_slow|error","frames":<int>,"pcm_sha256":"<hex>"}`

- `network_too_slow` : le client a arrêté la capture car la WebSocket accumulait plus de ~5 s
  d'audio non envoyé (`bufferedAmount`). Le hash est présent et vérifié comme pour `manual`.

- `pcm_sha256` = SHA-256 de `wavBytes.subarray(44)` (partie audio du WAV produit par `stop()`).
- Absent quand `reason` vaut `error` (le module ne produit pas de WAV après une erreur).

## Serveur → client

| Message | Contenu |
| --- | --- |
| `ready` | `{"type":"ready","session_id":…,"profile":…,"server_time":<epoch s>}` |
| `error` | `{"type":"error","code":…,"message":…}` puis fermeture (code 1008) |
| `pong` | `{"type":"pong","t":…}` |
| `stats` | chaque seconde : `packets_per_s`, `audio_s`, `rt_ratio`, `kbps`, `peak_dbfs`, `rms_dbfs` (`null` = silence numérique), `max_gap_ms`, `gaps` |
| `end_ack` | `{"type":"end_ack","frames_received":N,"pcm_sha256":"<hex>","match":true\|false,"profile":…}` puis fermeture |

`match` est vrai si et seulement si le hash **et** le nombre d'échantillons du client égalent ceux
calculés par le serveur sur les octets reçus.

`profile` est renvoyé dans `ready` et dans `end_ack`. Le client logue une erreur s'il diffère du profil envoyé.

## Validation côté serveur

`hello` : `protocol` connu ; `capture_contract` ∈ {`edth.web-pcm.v1`, `edth.web-pcm.webkit.v1`} ;
`sample_rate == 48000`, `channels == 1`, `sample_format == "pcm_s16le"`,
`channel_selection == "first"`, `recorder == "audio_worklet_pcm"` (égalité stricte de type) ;
`session_id` UUID valide ; `profile` ∈ liste ci-dessus (chaîne exacte, sensible à la casse).

Paquets : au moins 6 octets, partie audio de longueur paire, `seq` égal à la valeur attendue.

Codes d'erreur : `invalid_hello`, `unknown_protocol`, `unknown_profile`, `unknown_contract`, `invalid_format`,
`invalid_packet`, `discontinuity`, `unexpected_message`, `session_replaced`.

`session_replaced` : une session plus récente a démarré avec le même `profile` (la plus récente gagne).
L'ancienne reçoit cette erreur puis la fermeture 1008, donc le client ne la relance pas. Cela évite
de bloquer une reconnexion tant que le serveur n'a pas vu la fin de l'ancienne connexion (coupure
brutale), et deux onglets ouverts sur le même profil ne se relancent pas l'un l'autre en boucle.

## État général : `/ws/state` (serveur → client, lecture seule)

À la connexion puis toutes les `STATE_PERIOD_MS` (250 ms par défaut), le serveur envoie l'état de tous les téléphones du contrat, dans
l'ordre de `contracts/profiles.json`. Les messages du client sont ignorés.

```json
{ "type": "state", "server_time": <epoch s>, "estimator": "none|scripted|model", "drone": { … } | null,
  "phones": [
    { "profile": "noe", "label": "Téléphone de Noé", "position_m": {"x": 2.06, "y": 9.66, "z": 0},
      "status": "streaming|stale|offline|never_seen", "session_id": "…|null", "contract": "…|null",
      "last_seen_age_s": 0.04, "rt_ratio": 1.0, "rms_dbfs": -42.1,
      "detection": null } ] }
```

| `status` | Condition |
| --- | --- |
| `streaming` | session ouverte, dernier paquet il y a ≤ `STALE_AFTER_MS` (1 s par défaut) |
| `stale` | session ouverte, aucun paquet depuis plus de `STALE_AFTER_MS` |
| `offline` | aucune session ouverte ; `last_seen_age_s` = temps écoulé depuis la dernière activité |
| `never_seen` | aucune session depuis le démarrage du serveur |

`session_id`, `contract`, `rt_ratio`, `rms_dbfs` et `detection` valent `null` hors session.
`rt_ratio` et `rms_dbfs` restent `null` jusqu'aux premières statistiques.

`detection` vaut `null` sans estimateur (`estimator: "none"`) ou avant la première fenêtre complète
(`scripted` : `DISTANCE_WINDOW_MS`, 250 ms par défaut, fenêtres contiguës ; `model` : une estimation par
période `MODEL_PERIOD_MS`, voir plus bas).
Sinon : `{"drone": bool, "distance_m": float|null, "uncertainty_rel": float|null, "age_s": float,
"fresh": bool}`. `distance_m` et `uncertainty_rel` ne sont présents que si `drone` est vrai.
`fresh` est vrai si la détection a ≤ `DETECTION_FRESH_MS` (2 s par défaut).

L'estimateur se choisit avec `DISTANCE_ESTIMATOR` : `none` par défaut, `scripted` (mock de ②, drone
virtuel sur une trajectoire connue) ou `model` (vrai modèle, release du repo ML).

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `DISTANCE_ESTIMATOR` | `none` | `none`, `scripted` ou `model` |
| `DISTANCE_WINDOW_MS` | 250 | taille d'une fenêtre analysée par le mock (`model` : imposé par la release) |
| `STATE_PERIOD_MS` | 250 | intervalle entre deux messages `state` |
| `STALE_AFTER_MS` | 1000 | seuil `streaming` → `stale` |
| `DETECTION_FRESH_MS` | 2000 | âge maximal d'une détection `fresh` |
| `FUSION_SPREAD_MS` | 500 | écart maximal entre les détections combinées par ③ (zone brute, démarrage de la piste) |
| `TRACK_ACCEL_STD` | 1.0 | piste : accélération non modélisée (m/s²) ; plus grand = plus réactif, plus petit = plus lisse |
| `TRACK_TIMEOUT_MS` | 1000 | piste perdue sans distance acceptée depuis ce délai |
| `TRACK_ALTITUDE_M` | 1.5 | piste : altitude attendue du drone (≥ 0) |
| `TRACK_ALTITUDE_STD_M` | 0.5 | piste : souplesse de cette altitude (écart-type) |
| `TRACK_MAX_RADIUS_M` | 1.0 | piste : rayon maximal ; au-delà, une piste confirmée est abandonnée |
| `SCRIPTED_OFFSET_EAST_M` | 0.5 | drone simulé : centre du cercle, décalage vers l'est depuis le barycentre des téléphones |
| `SCRIPTED_OFFSET_NORTH_M` | 3 | idem vers le nord (y décroissant) |
| `SCRIPTED_RADIUS_M` | 3 | rayon du cercle |
| `SCRIPTED_ALTITUDE_M` | 1.5 | altitude (≥ 0) |
| `SCRIPTED_PERIOD_S` | 20 | durée d'un tour |
| `SCRIPTED_RANGE_M` | 5 | portée de détection : au-delà, « pas de drone » |
| `SCRIPTED_UNCERTAINTY` | 0.10 | incertitude relative annoncée avec chaque distance |
| `DISTANCE_MODEL_REPO` | — | `model` : repo Hugging Face des releases (ex. `ImAPancake/EDTH_ml_models`) |
| `DISTANCE_MODEL_REVISION` | — | `model` : sha de commit HF à 40 caractères, épinglé (jamais une branche) |
| `DISTANCE_MODEL_RELEASE` | — | `model` : dossier de la release dans le repo (ex. `edth.audio.48k-w100.r1`) ; le manifeste doit porter ce nom |
| `DISTANCE_MODEL_DIR` | — | `model` : bundle local (dev, hors ligne) ; prioritaire, les trois variables précédentes sont alors inutiles |
| `MODEL_UNCERTAINTY` | 0.10 | `model` : incertitude relative annoncée avec chaque distance (le contrat ML la laisse à l'appli) |
| `MODEL_PERIOD_MS` | 100 | `model` : cadence des estimations, multiple du pas de la release (r1 : 20 ms) ; le modèle n'évalue que la dernière fenêtre de chaque période |
| `HF_TOKEN` | — | jeton Hugging Face (repo privé) ; jamais journalisé |
| `SCRIPTED_NOISE` | 0 | écart-type relatif d'un bruit gaussien sur chaque distance (0 = exacte ; 0.05 ≈ 95 % des distances dans ± 10 %). La détection reste décidée sur la vraie distance. |

Les durées `*_MS` sont des entiers strictement positifs en millisecondes ; les autres valeurs sont des
réels (point décimal). Une valeur invalide empêche le serveur
de démarrer (message d'erreur nommant la variable).
### Vrai modèle : `DISTANCE_ESTIMATOR=model`

Contrat d'intégration ML v2 (Outline « Contrat d'intégration ML — bundle de release, manifeste et
inférence live »). Une release est un dossier : `manifest.json` (`edth.model-release.v2`), `frozen/`
(`dsp.py`, `features.py`, `ml.py`), `detection/` et `distance/model.joblib`, `parity/fixture.json`.
Release en service : `edth.audio.48k-w100.r1` (48 kHz natif sans FIR, fenêtres de 100 ms toutes les
20 ms, 50 niveaux de bandes, détection et distance par MLP). La r0 (contrat v1) n'est plus chargeable.

- **Chargement au démarrage** : `DISTANCE_MODEL_DIR`, sinon téléchargement du seul dossier
  `DISTANCE_MODEL_RELEASE` du repo à la révision épinglée (cache `HF_HOME`). Pour tirer la release au
  déploiement plutôt qu'au premier démarrage : `python -m api.model_fetch` (mêmes variables).
- **Refus, jamais de repli sur le mock** : contrat autre que v2, transport autre que 48 kHz mono s16le,
  taux inconnu de `dsp.py`, FIR annoncé différent de celui de `dsp.py` (`null` à 48 kHz), fenêtres qui
  ne finissent pas sur le pas, seuil hors ]0, 1[, `features.local_only` faux, argument de
  `features.recompute` inconnu de `dsp.window_features` ou groupe de bandes inconnu, `columns` du
  manifeste différentes de celles des pickles, `frozen/*.py` différents de `packages/features` (vérifié
  avant de charger les pickles), dossier qui contient une autre release, `MODEL_PERIOD_MS` qui n'est pas
  un multiple du pas, lot de parité non reproduit. Le serveur ne démarre pas et l'erreur nomme la cause
  (log `event=model_loaded release=… source=… revision=… period_ms=…` en cas de succès).
- **Parité** : chaque cas du lot (une session : amorce 500 ms + une fenêtre) est rejoué par le chemin
  live et doit redonner la fenêtre (après décimation éventuelle) à l'octet près, la même recette
  (`window_ms`, `recompute`), les features à 1e-9, le score à 1e-6 et la même présence (la distance n'est
  comparée que si le drone est présent).
- **Chemin live** (par session, état neuf à chaque session) : décimation continue si le taux modèle
  l'exige (état FIR conservé ; aucune à 48 kHz), fenêtres glissantes (r1 : 100 ms, pas de 20 ms),
  features recalculées par `dsp.window_features(…, window_ms, **recompute)`, contrôle qualité sur le flux
  48 kHz (suite de zéros exacts ≥ 40 ms → fenêtres touchées et garde de 500 ms exclues).
- **Cadence (`MODEL_PERIOD_MS`, réglage de l'appli, 100 ms par défaut)** : le serveur reçoit des blocs
  d'une période et n'évalue que la dernière fenêtre de chacun ; décimation et contrôle qualité voient
  tous les échantillons, les fenêtres évaluées sont donc celles du hors ligne. Chaque période donne une
  `detection` : fenêtre non analysable (amorce, coupure) ou score < seuil → `drone: false` ; sinon
  `distance_m` (bornée par le modèle à [1, 5] m) et `MODEL_UNCERTAINTY`. Mesure (r1, 3 téléphones) :
  ≈ 13 % d'un cœur à 100 ms, ≈ 65 % à 20 ms (chaque fenêtre). Motif d'une fenêtre non analysable
  journalisé à chaque changement (`event=model_window_skipped profile=… reason=warmup|dropout`).
- **Écart causal connu** : une suite de zéros encore trop courte à la fin d'une fenêtre ne l'invalide pas,
  alors que hors ligne elle est vue en entier. En r1 (pas de 20 ms < coupure minimale de 40 ms), cela
  concerne au plus les deux fenêtres qui finissent dans les 40 premières ms de chaque coupure.

### `drone` : résultat de ③

`null` sans estimateur ou avant le premier calcul. Sinon, recalculé toutes les `STATE_PERIOD_MS` :

```json
{ "status": "located|insufficient|no_detection|inconsistent", "detecting": 3, "age_s": 0.1,
  "zone": { "x_m": 3.1, "y_m": 7.9, "radius_m": 0.8, "z_m": 1.4, "z_min_m": 1.1, "z_max_m": 1.7,
            "tolerance": 0.1, "degraded": false } | null,
  "track": { "x_m": 3.0, "y_m": 8.1, "z_m": 1.5, "vx_mps": 0.3, "vy_mps": -0.4, "radius_m": 0.4,
             "z_min_m": 1.2, "z_max_m": 1.8 } | null,
  "truth": { "x_m": 3.0, "y_m": 8.0, "z_m": 1.5 } | null }
```

- Détections combinées : dernière détection **avec distance** de chaque téléphone en session, fraîche
  (≤ `DETECTION_FRESH_MS`) et à ≤ `FUSION_SPREAD_MS` de la plus récente. `detecting` = leur nombre.
- `located` (`zone` présente) : au moins 3 détections et `localiser_drone` trouve une zone ;
  `insufficient` : 1 ou 2 ; `no_detection` : 0 ; `inconsistent` : 3 ou plus mais distances incompatibles.
- `zone` : repère de la salle (x vers l'est, y vers le sud, mètres) ; disque `radius_m` autour de
  (`x_m`, `y_m`), altitude `z_m` dans [`z_min_m`, `z_max_m`] ; `tolerance` = plus grande incertitude des
  détections, élargie si `degraded`.
- `track` : piste du drone, filtre de Kalman étendu (`packages/localization/tracking.py`) sur les
  distances, une correction par détection nouvelle, à son instant ; indépendante de `status` (elle se
  poursuit avec 1 ou 2 téléphones tant qu'elle reste précise). Démarre sur la `zone` d'un tick qui
  apporte des détections nouvelles ; repart de la zone après 5 distances rejetées d'affilée (test χ² à
  99 %). Jugée une fois par tick : `null` tant que son rayon dépasse `TRACK_MAX_RADIUS_M` (piste
  provisoire, ou trop imprécise : un seul téléphone situe le drone sur un cercle, pas le long de ce
  cercle) ; une piste confirmée qui le dépasse est abandonnée (seule une zone la relance) ; perdue
  aussi sans distance acceptée depuis `TRACK_TIMEOUT_MS`. Position et vitesse horizontale prédites à
  l'instant du calcul ; disque `radius_m` = 2 σ ; altitude tirée vers `TRACK_ALTITUDE_M` (téléphones
  coplanaires : les distances seules disent peu de z) et jamais sous le sol. L'incertitude relative d'une
  distance est lue comme une borne à ≈ 2 σ.
- `truth` : position vraie du drone simulé (`DISTANCE_ESTIMATOR=scripted`), pour vérifier la chaîne ;
  `null` sinon.

## Enregistrement (`SAVE_SESSIONS=1`)

`$RECORDINGS_DIR/<profile>_<session_id>.wav` (par défaut `./recordings/`). Les logs `session_start` et
`session_end` portent `profile=…`.

## Définitions des statistiques

- `rt_ratio` = secondes d'audio reçues ÷ temps écoulé depuis `ready` (cumulé ; inclut la latence
  de démarrage, converge vers 1,00).
- `kbps` = débit PCM utile de la dernière seconde (attendu ≈ 768).
- `peak_dbfs`, `rms_dbfs` : dBFS relatifs à 32 768, dernière seconde.
- `max_gap_ms` : plus grand intervalle entre deux paquets ; `gaps` : intervalles > 150 ms.

Ces mesures sont du diagnostic : elles ne modifient jamais les octets reçus ou enregistrés.

## Relances côté client

Chaque relance ouvre une nouvelle capture et une nouvelle session (nouvel UUID) ; le log
`micro ok … gap_ms=` donne le trou réel depuis la fin de la session précédente.

| Fin de session | Suite |
| --- | --- |
| `limit` | relance immédiate |
| coupure WebSocket (hors 1008), `network_too_slow` | reconnexion après 1, 2, 4, 8, 16 puis 30 s (plafond), sans limite d'essais ; le délai repart de 1 s dès qu'une session reçoit `ready` |
| refus serveur (fermeture 1008), erreur du module, micro refusé | arrêt, état erreur, aucune relance |

Le bouton Arrêter annule une reconnexion en attente.

## Évolutions prévues (non implémentées)
- Importer les validateurs de `collector/contract.py` quand il sera extrait du collecteur.
