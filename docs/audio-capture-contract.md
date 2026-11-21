# Contrat de capture web commun à la collecte et à l’inférence

**Versions : `edth.web-pcm.v1` (strict) et `edth.web-pcm.webkit.v1` (WebKit à vérification partielle).** La capture du futur produit web doit réutiliser le cœur [audio_capture.js](<../collector/audio_capture.js>), pas une implémentation seulement « équivalente ». Le collecteur reste Streamlit ; seul le microphone a un adaptateur JavaScript. Les profils, étiquettes, fichiers, lecteurs natifs, tableau et synchronisation ne changent pas.

## Paramètres du signal

| Élément | Profil strict (différences WebKit détaillées plus bas) |
| --- | --- |
| Acquisition | `navigator.mediaDevices.getUserMedia`, une piste audio, aucune vidéo |
| Annulation d’écho | `echoCancellation: { exact: false }` |
| Réduction de bruit | `noiseSuppression: { exact: false }` |
| Gain automatique | `autoGainControl: { exact: false }` |
| Canaux demandés à la source | `channelCount: { ideal: 1 }` ; conserver le nombre effectivement rapporté |
| Sélection des canaux | Premier canal logique uniquement, sans moyenne, mélange ni compensation de volume |
| Fréquence de sortie | Contexte Web Audio explicitement à **48 000 Hz**, vérifié |
| Capture | AudioWorklet ; aucune utilisation de MediaRecorder, Opus, AAC ou autre codec destructif |
| Échantillons | **Mono PCM signé 16 bits**, little-endian (`pcm_s16le`) |
| Transformations exclues | Aucun filtre vocal applicatif, gain, normalisation par prise/fenêtre, compresseur ou rééchantillonnage applicatif supplémentaire |
| Fichier de collecte | WAV RIFF encapsulant ces mêmes échantillons PCM ; aucune reconversion après réception |

Le navigateur peut convertir la fréquence de la source vers celle du contexte à 48 kHz. Ce n’est donc **pas** une promesse de sortie ADC bit à bit : le même chemin Web Audio et la même conversion doivent être employés des deux côtés. La fréquence de la piste, lorsqu’elle est exposée, reste dans `track_settings` ; Firefox peut ne pas l’exposer. Ne pas la déduire de l’en-tête WAV.

### Pourquoi choisir le premier canal ?

Une source peut rester stéréo lorsque les traitements vocaux sont coupés, malgré une préférence mono. La sortie doit néanmoins être mono de manière déterministe : sélectionner le canal logique 0 **sans faire de moyenne des canaux**. Cela conserve son amplitude et évite une annulation entre canaux en opposition de phase. Cette règle est identique en collecte et en inférence ; elle ne choisit pas un microphone physique caché à l’intérieur d’un téléphone.

### Quantification de référence

Pour chaque flottant Web Audio : valeur non finie → zéro ; limitation à `[-1, 1]` ; `Math.round(x * 32768)` si `x < 0`, sinon `Math.round(x * 32767)`. Cette conversion S16 du cœur partagé fait foi. L’inférence consomme ces **mêmes S16**, pas un autre export flottant avec un gain ou une normalisation supplémentaire.

## Profil iPhone / WebKit à vérification partielle

**Décision explicitement acceptée le 20 novembre 2026 :** permettre un profil distinct sans prétendre qu’il est certifié brut ni équivalent au contrat strict. Le signal PCM, le premier canal, la quantification, l’AudioWorklet et les règles d’interruption sont communs ; les preuves de désactivation DSP diffèrent.

WebKit Apple ne publie pas les commandes indépendantes `noiseSuppression` et `autoGainControl`, ni le nombre de canaux dans `getSettings()`. Le [changement WebKit de janvier 2023](https://github.com/WebKit/WebKit/commit/1796e2f138aba9c879d20e49e6458ae7e3fef898) décrit explicitement le chemin **RemoteIO sur iOS / HAL sur macOS lorsque l’anti-écho est désactivé**, au lieu de VoiceProcessingIO. Ce chemin évite l’unité de traitement vocal ; il ne prouve pas séparément des réglages NS/AGC que l’API n’expose pas, ni l’absence de traitements système/matériel. Le code JavaScript ne peut pas inspecter l’unité native réellement instanciée.

### Sélection et contrôles

- Si les trois commandes sont reconnues, conserver le contrat strict, même sur iPhone : aucun assouplissement d’un contrôle strict après échec.
- Sinon, uniquement pour un agent Apple WebKit identifié (iPhone/iPad/iPod, ou Safari Macintosh comme l’iPad en mode bureau), et si `echoCancellation` est reconnu : sélectionner `edth.web-pcm.webkit.v1`. Le user-agent sert au routage, **pas à certifier le moteur ou le matériel**. Les autres moteurs restent refusés s’ils ne reconnaissent pas les trois commandes.
- Demander **`echoCancellation:false`**, puis exiger `getSettings().echoCancellation === false`, au début **et** à l’arrêt. La forme booléenne contourne le [bug WebKit avec `{exact:false}`](https://github.com/WebKit/WebKit/commit/7f097e69658b94b477ef4a790e79fad82cefc6c6), corrigé dans les branches Safari 18.4 ; **la postcondition n’est jamais assouplie**. Il n’y a ni seconde ouverture du micro ni retry avec AEC actif.
- Les demandes NS/AGC `{exact:false}` restent présentes ; WebKit peut les ignorer. Ne pas confondre `requested_constraints` avec une preuve d’application. Chaque réglage rapporté doit être exactement `false` ; un réglage absent n’est admissible que s’il n’est pas annoncé reconnu. Un réglage vrai, `null`, `0` ou `"false"` est refusé. Un anti-écho absent est toujours refusé.
- `getSupportedConstraints()` indique des noms reconnus, pas les capacités du microphone. La preuve retenue reste le réglage effectif rapporté après ouverture. Une absence/erreur de confirmation ferme le micro et ne sauvegarde pas de prise partielle.
- `channelCount` absent est autorisé uniquement pour ce profil : `input_channels:null`. Un nombre présent doit être entier positif ; il n’est jamais inventé à partir du WAV mono. L’AudioWorklet sélectionne toujours `inputs[0][0]`, sans moyenne.
- Un avertissement est affiché avant capture et après sauvegarde. Le serveur vérifie séparément les deux contrats. Un changement de réglages DSP/nombre de canaux rapportés entre début et arrêt invalide la prise.

### Provenance et entraînement

```json
{
  "capture_contract": "edth.web-pcm.webkit.v1",
  "processing_verification": "webkit_echo_cancellation_only",
  "echoCancellation": false,
  "noiseSuppression": null,
  "autoGainControl": null,
  "input_channels": null,
  "supported_constraints": { "echoCancellation": true },
  "track_settings": { "echoCancellation": false, "sampleRate": 48000 },
  "system_processing": "unverified"
}
```

Exemple réduit : le rapport réel et toutes les contraintes demandées sont conservés intégralement. Dans `track_settings`, les clés absentes restent absentes ; seuls les champs de synthèse deviennent `null`, jamais `false` par supposition. Si WebKit expose à l’avenir une valeur `false`, elle reste `false` et n’est pas remplacée par `null`.

**Ne pas fusionner automatiquement les deux contrats pour l’entraînement.** Filtrer explicitement `capture_settings.capture_contract`, et valider séparément les prises WebKit face au futur profil d’inférence WebKit. La synchronisation conserve tous les profils et les valeurs inconnues. L’inférence doit appeler ce même cœur et conserver le contrat effectivement choisi, pas forcer les flags inconnus à `false`.

### Validation iPhone restant à faire

Les tests automatisés simulent les réponses API WebKit, y compris l’absence de NS/AGC/canaux, et contrôlent le PCM réellement écrit sous Chromium/Firefox. **Ce n’est pas une exécution Safari iOS ni un test de vrai microphone iPhone.** Sur l’appareil : Safari/iOS à jour, HTTPS direct (pas de navigateur intégré), micro intégré, pas de Bluetooth ; éviter le mode système « Isolation de la voix » et préférer « Standard » si proposé. Enregistrer un même son externe à niveau et position constants, proche puis éloigné, puis écouter le fichier sauvegardé. Pas de garantie écran verrouillé. Les versions anciennes peuvent ne pas offrir le même chemin natif : recommander une mise à jour plutôt qu’affirmer RemoteIO pour toutes les versions historiques.

Ne pas modifier `navigator.audioSession.type` pour prétendre désactiver un DSP : cette API règle une catégorie de session, pas NS/AGC ni le choix de l’unité native. Aucune amplification de compensation n’est ajoutée.

## Vérifier le profil strict avant de collecter

1. HTTPS (ou localhost), AudioWorklet et les trois contraintes de traitement doivent être reconnus.
2. Demander les trois désactivations comme contraintes obligatoires, sans repli silencieux sur les réglages par défaut.
3. Vérifier `track.getSettings()` : les trois valeurs doivent être **exactement `false`**. Une valeur absente, `null`, vraie, `0` ou la chaîne `"false"` ne constitue pas cette confirmation.
4. Vérifier piste disponible/non coupée et contexte à 48 kHz. Une interruption, une suspension ou une déconnexion invalide la prise ; pas de sauvegarde partielle présentée comme complète.
5. Le serveur revalide le contrat, l’identité de la prise, les métadonnées et le WAV mono PCM16 à 48 kHz.

Un signal très calme n’est **pas** rejeté : les exemples négatifs peuvent légitimement être silencieux. Le diagnostic de niveau est une mesure, jamais un ajustement du fichier.

## Réutilisation dans le produit web

Le cœur exporte `CAPTURE_CONTRACT`, `WEBKIT_CAPTURE_CONTRACT`, leurs contraintes respectives, `getCaptureSupport`, `createPcmCapture`, la quantification S16 et l’encapsulation WAV. `start().captureSettings.capture_contract` indique le profil réellement choisi ; la constante stricte seule ne représente pas un navigateur WebKit à vérification partielle. Il ne dépend ni de Streamlit, ni des labels, ni de Hugging Face.

```javascript
import { CAPTURE_CONTRACT, createPcmCapture } from './audio_capture.js';

const capture = createPcmCapture({
  onChunk({ samples, sampleRate, channels, sampleFormat }) {
    // samples est un Int16Array : mêmes valeurs que dans le WAV d’entraînement.
    // Accumuler des fenêtres contiguës ; ne pas normaliser ni réencoder avec Opus.
    // Le transport vers le moteur d’inférence appartient au produit, pas au collecteur.
  },
  onError(error) {
    // Afficher l’échec ; ne pas passer silencieusement à un autre mode de capture.
  },
});

// À appeler sur un geste utilisateur, après sélection du micro par le navigateur.
await capture.start();
// À la fin : await capture.stop(); puis capture.dispose() au démontage.
```

L’intégration du produit final n’existe pas dans ce dépôt et n’est donc pas annoncée testée. Elle doit importer ce module, conserver les vérifications et exposer le même identifiant de contrat. L’accumulation des fenêtres, le transport et l’éventuelle absence d’encapsulation WAV à l’inférence ne doivent pas changer les échantillons.

- Une fenêtre de 500 ms contient 24 000 échantillons ; une fenêtre de 1 s, 48 000. Ne pas redémarrer le micro pour chaque fenêtre.
- Le cœur actuel borne une prise de collecte à 16 Mio, soit environ 175 s. Cette protection de stockage n’est pas une taille de fenêtre de modèle. Une adaptation pour une inférence continue doit modifier uniquement la rétention/le transport des chunks, pas l’acquisition ou la quantification.
- Si le modèle utilise une autre fréquence, un autre fenêtrage ou une transformation supplémentaire, employer **la même fonction de prétraitement** à l’entraînement et à l’inférence. Rien de tel n’est ajouté par ce collecteur.
- Modifier des contraintes, la règle de canal, la quantification ou la fréquence impose une nouvelle version du contrat et une validation correspondante des données/modèles.

## Provenance, anciens samples et navigateurs

Chaque nouvelle prise conserve le contrat, le navigateur, le libellé du micro, les contraintes demandées, les réglages réellement rapportés, le nombre de canaux en entrée, le format de sortie et la date de début côté navigateur. Les étiquettes et l’UUID restent figés avant le départ ; la date et le payload restent identiques lors d’un retry.

Les anciens fichiers ne sont ni modifiés ni supprimés. Les prises `streamlit.audio_input` ont pu passer par Opus et des traitements vocaux inconnus ; les anciennes prises sans identifiant de contrat ne prouvent pas non plus la conformité v1. **Pour un entraînement devant correspondre au nouveau produit, sélectionner explicitement `capture_settings.capture_contract == "edth.web-pcm.v1"`.** Ne pas fusionner silencieusement ces chaînes de capture. Le dashboard et la synchronisation continuent de montrer/publier tout le dataset, sans quota ni exclusion automatique.

Chromium est la référence recommandée pour homogénéiser collecte et produit. Firefox moderne peut satisfaire le même contrat ; son support doit être vérifié à l’exécution, et les tests avec micro simulé ne certifient pas les appareils physiques. Conserver les versions de navigateur et la même entrée physique autant que possible. Les `deviceId` sont propres à l’origine web : ne pas les copier aveuglément entre domaines.

Le profil WebKit accepté le 20 novembre n’est pas automatiquement équivalent au profil strict : ses preuves DSP et ses valeurs inconnues restent identifiables même si les octets PCM suivent le même format. Les deux peuvent alimenter des profils d’inférence correspondants après validation explicite, pas par mélange implicite.

## Limite importante : ce n’est pas une certification du matériel

`system_processing: "unverified"` reste explicite. Pour le profil strict, les trois valeurs `false` attestent seulement les réglages rapportés par le navigateur ; le profil WebKit ne confirme séparément que l’anti-écho et conserve les autres réglages inconnus. Un pilote, le système ou le firmware peut encore appliquer un traitement non exposé. Chromium décrit notamment un chemin Android conservant un AGC système lorsque l’anti-écho est coupé. **Même code web ne signifie ni microphones identiques, ni garantie d’absence de DSP système.**

Ne pas promettre qu’un passage à Chrome supprime cette limite. Vérifier l’entrée choisie, éviter Bluetooth/les microphones virtuels traités pour la référence, couper les améliorations audio du système lorsqu’elles sont accessibles, puis comparer réellement le même son à position et volume constants. Le niveau et le comportement à distance restent des mesures terrain, pas des garanties d’un test synthétique.

## Références

- [Spécification Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/)
- [getSettings : valeurs réellement rapportées](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getSettings)
- [Chromium : routage Android et AGC résiduel, août 2026](https://chromium.googlesource.com/chromium/src/+/054d2dca6293ac1847a8287491a18593c047cc50)
- [Documentation du collecteur](<../README.md>)
