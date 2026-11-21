/** Textes affichés par la page d'état (aucun calcul de domaine : tout vient du serveur). */
import type { Detection, DroneView, EstimatorName, PhoneState, PhoneStatus, Zone } from "./state";

const STATUS_LABELS: Record<PhoneStatus, string> = {
  streaming: "À l'écoute",
  stale: "Réseau lent",
  offline: "Hors ligne",
  never_seen: "Jamais connecté",
};

export function statusLabel(status: PhoneStatus): string {
  return STATUS_LABELS[status];
}

const SHORT_STATUS: Record<PhoneStatus, string> = {
  streaming: "Écoute",
  stale: "Lent",
  offline: "Hors ligne",
  never_seen: "Jamais",
};

/** État en un mot, pour le tableau des capteurs. */
export function shortStatus(status: PhoneStatus): string {
  return SHORT_STATUS[status];
}

export function listeningText(phones: readonly PhoneState[]): string {
  return `${phones.filter((p) => p.status === "streaming").length}/${phones.length} à l'écoute`;
}

/** Prénom affiché sur le plan : dernier mot du libellé du contrat (« Téléphone de Noé » → « Noé »). */
export function shortName(label: string): string {
  return label.split(" ").at(-1) as string;
}

/** Heure du serveur (epoch s), 24 h UTC suffixée Z. */
export function utcClock(epochS: number): string {
  return `${new Date(epochS * 1000).toISOString().slice(11, 19)}Z`;
}

export function ageText(ageS: number | null): string {
  if (ageS === null) return "—";
  if (ageS < 1) return "à l'instant";
  if (ageS < 60) return `il y a ${Math.round(ageS)} s`;
  return `il y a ${Math.floor(ageS / 60)} min`;
}

export function levelText(rmsDbfs: number | null): string {
  return rmsDbfs === null ? "—" : `${Math.round(rmsDbfs)} dBFS`;
}

export function detectionText(detection: Detection | null, estimator: EstimatorName): string {
  if (detection === null) return estimator === "none" ? "Pas d'estimateur" : "En attente de son";
  return detection.drone ? `Drone à ${rangeText(detection, estimator)}` : "Aucun drone";
}

/** Distance et marge, pour le tableau ; sinon la raison en un mot ou deux. */
export function rangeText(detection: Detection | null, estimator: EstimatorName): string {
  if (detection === null) return estimator === "none" ? "—" : "En attente";
  if (!detection.drone) return "Aucun drone";
  const metres = detection.distance_m.toFixed(1).replace(".", ",");
  return `${metres} m ± ${Math.round(detection.uncertainty_rel * 100)} %`;
}

/** Longueur en mètres, virgule décimale, une décimale. */
export function metres(value: number): string {
  return `${value.toFixed(1).replace(".", ",")} m`;
}

const REQUIRED_PHONES = 3; // localiser_drone a besoin de 3 distances (services/api/fusion.py)

const phones = (n: number) => `${n} téléphone${n > 1 ? "s" : ""}`;

export function droneStatusText(drone: DroneView | null, estimator: EstimatorName): string {
  if (drone === null) return estimator === "none" ? "Pas d'estimateur" : "En attente du premier calcul";
  switch (drone.status) {
    case "located":
      return `Localisé (${phones(drone.detecting)})`;
    case "insufficient":
      return `${phones(drone.detecting)} ${drone.detecting > 1 ? "détectent" : "détecte"}, ${REQUIRED_PHONES} nécessaires`;
    case "no_detection":
      return "Aucun téléphone ne détecte le drone";
    case "inconsistent":
      return "Distances incompatibles entre elles";
  }
}

export type Tone = "hostile" | "warn" | "off";

const TRACK_BADGES: Record<DroneView["status"], { text: string; tone: Tone }> = {
  located: { text: "Localisée", tone: "hostile" },
  insufficient: { text: "Non localisée", tone: "warn" },
  inconsistent: { text: "Incohérente", tone: "warn" },
  no_detection: { text: "Aucune détection", tone: "off" },
};

/** Badge de la piste (barre d'état et panneau) : un mot et une couleur de sens (Vigie C2). */
export function trackBadge(drone: DroneView | null, estimator: EstimatorName): { text: string; tone: Tone } {
  if (drone === null) return { text: estimator === "none" ? "Pas d'estimateur" : "En attente", tone: "off" };
  return TRACK_BADGES[drone.status];
}

export function zoneText(zone: Zone): string {
  return `x ${metres(zone.x_m)} · y ${metres(zone.y_m)} · ± ${metres(zone.radius_m)}`;
}

export function altitudeText(zone: Zone): string {
  return `${metres(zone.z_m)} (${metres(zone.z_min_m).slice(0, -2)} à ${metres(zone.z_max_m)})`;
}

/** Écart horizontal entre le centre calculé et le drone simulé ; null hors simulation ou sans position. */
export function truthErrorText(drone: DroneView): string | null {
  if (drone.truth === null || drone.zone === null) return null;
  return metres(Math.hypot(drone.zone.x_m - drone.truth.x_m, drone.zone.y_m - drone.truth.y_m));
}
