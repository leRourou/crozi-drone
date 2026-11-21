# Crozidrone

Détecter un drone et estimer sa position à partir des micros de plusieurs téléphones
(EDTH Paris 2026). Chaque téléphone envoie son son en temps réel ; une IA en déduit la distance
au drone, puis les distances sont combinées pour localiser le drone sur une carte.

## Modules

| Module | Rôle | État |
| --- | --- | --- |
| `packages/audio-capture` | ① Récupération du son des téléphones | ✅ |
| `packages/distance-estimation` | ② IA : son → distance au drone | 🧪 mock (trajectoire scriptée), modèle à venir |
| `packages/localization` | ③ Distances + positions des sources → position du drone | 🟡 `localiser_drone` testé, pas encore branché sur l'API |
| `web/src/display` | ④ Affichage des sources sonores et de la position du drone | 🟡 page d'état (téléphones, détection, distance) ; position à venir |
| `services/api` | Assemble les modules et sert l'application web | ✅ |

Hors périmètre : iPhone / Safari (le profil WebKit est accepté mais non validé).

## audio-capture

Reçoit en temps réel, par WebSocket, le son du micro des téléphones : PCM mono 48 kHz 16 bits,
identique octet pour octet aux données d'entraînement, puisque la capture se fait avec le module
partagé du collecteur (`vendor/edth/`). Le module vérifie le format, la continuité du flux et
l'intégrité des données (SHA-256), et calcule des statistiques de réception en direct.
La page téléphone associée se trouve dans `web/src/capture`.

Détails : [protocole](docs/protocol.md) · [contrat de capture](docs/audio-capture-contract.md).

## État général

`display.html` (à ouvrir sur le PC de supervision) affiche chaque téléphone du contrat : connecté ou non,
drone détecté ou non, et à quelle distance. Les données viennent de `/ws/state`. En attendant le modèle,
`DISTANCE_ESTIMATOR=scripted` simule un drone virtuel sur une trajectoire connue (bandeau « Estimateur
simulé ») ; par défaut (`none`), aucune détection n'est affichée. L'état est rafraîchi toutes les 250 ms
(réglages en variables d'environnement : voir [protocole](docs/protocol.md)).
