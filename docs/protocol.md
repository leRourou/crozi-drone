# Protocole WebSocket `thc.audio-stream.v1`

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
{ "type": "hello", "protocol": "thc.audio-stream.v1", "session_id": "<uuid v4>",
  "capture_settings": { "…": "captureSettings renvoyé par start(), intégral" },
  "captured_at": "<ISO UTC>", "user_agent": "…" }
```

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
`{"type":"end","reason":"manual|limit|error","frames":<int>,"pcm_sha256":"<hex>"}`

- `pcm_sha256` = SHA-256 de `wavBytes.subarray(44)` (partie audio du WAV produit par `stop()`).
- Absent quand `reason` vaut `error` (le module ne produit pas de WAV après une erreur).

## Serveur → client

| Message | Contenu |
| --- | --- |
| `ready` | `{"type":"ready","session_id":…,"server_time":<epoch s>}` |
| `error` | `{"type":"error","code":…,"message":…}` puis fermeture (code 1008) |
| `pong` | `{"type":"pong","t":…}` |
| `stats` | chaque seconde : `packets_per_s`, `audio_s`, `rt_ratio`, `kbps`, `peak_dbfs`, `rms_dbfs` (`null` = silence numérique), `max_gap_ms`, `gaps` |
| `end_ack` | `{"type":"end_ack","frames_received":N,"pcm_sha256":"<hex>","match":true\|false}` puis fermeture |

`match` est vrai si et seulement si le hash **et** le nombre d'échantillons du client égalent ceux
calculés par le serveur sur les octets reçus.

## Validation côté serveur

`hello` : `protocol` connu ; `capture_contract` ∈ {`edth.web-pcm.v1`, `edth.web-pcm.webkit.v1`} ;
`sample_rate == 48000`, `channels == 1`, `sample_format == "pcm_s16le"`,
`channel_selection == "first"`, `recorder == "audio_worklet_pcm"` (égalité stricte de type) ;
`session_id` UUID valide.

Paquets : au moins 6 octets, partie audio de longueur paire, `seq` égal à la valeur attendue.

Codes d'erreur : `invalid_hello`, `unknown_protocol`, `unknown_contract`, `invalid_format`,
`invalid_packet`, `discontinuity`, `unexpected_message`.

## Définitions des statistiques

- `rt_ratio` = secondes d'audio reçues ÷ temps écoulé depuis `ready` (cumulé ; inclut la latence
  de démarrage, converge vers 1,00).
- `kbps` = débit PCM utile de la dernière seconde (attendu ≈ 768).
- `peak_dbfs`, `rms_dbfs` : dBFS relatifs à 32 768, dernière seconde.
- `max_gap_ms` : plus grand intervalle entre deux paquets ; `gaps` : intervalles > 150 ms.

Ces mesures sont du diagnostic : elles ne modifient jamais les octets reçus ou enregistrés.

## Évolutions prévues (non implémentées)
- `reason: "network_too_slow"` (arrêt si `bufferedAmount` > ~5 s d'audio) et reconnexion avec
  délai croissant.
- Importer les validateurs de `collector/contract.py` quand il sera extrait du collecteur.
