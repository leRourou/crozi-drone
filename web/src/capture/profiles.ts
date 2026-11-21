/**
 * Téléphones de l'équipe. Même liste d'identifiants que KNOWN_PROFILES dans
 * packages/audio-capture/src/audio_capture/protocol.py (référence : docs/protocol.md).
 */
export const PROFILES = [
  { id: "axel", label: "Téléphone d'Axel" },
  { id: "maxence", label: "Téléphone de Maxence" },
  { id: "tristan", label: "Téléphone de Tristan" },
  { id: "noe", label: "Téléphone de Noé" },
  { id: "charlene", label: "Téléphone de Charlène" },
] as const;

export type ProfileId = (typeof PROFILES)[number]["id"];
