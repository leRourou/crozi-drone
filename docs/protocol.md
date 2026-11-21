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
  "profile": "axel|maxence|tristan|noe|charlene",
  "capture_settings": { "…": "captureSettings renvoyé par start(), intégral" },
  "captured_at": "<ISO UTC>", "user_agent": "…" }
```

`profile` : téléphone de l'équipe choisi sur la page avant d'enregistrer (obligatoire, non mémorisé).
Identifiants ASCII stables. Les libellés affichés sont « Téléphone d'Axel », « … de Maxence », « … de Tristan »,
« … de Noé » et « … de Charlène ». **Ce document est la référence** de la liste, dupliquée dans
`web/src/capture/profiles.ts` et `KNOWN_PROFILES` (`audio_capture/protocol.py`). Une relance après la
limite du module garde le profil.

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
`invalid_packet`, `discontinuity`, `unexpected_message`.

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
