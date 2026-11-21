/** Textes affichés par la page d'état (aucun calcul de domaine : tout vient du serveur). */
import type { Detection, EstimatorName, PhoneStatus } from "./state";

const STATUS_LABELS: Record<PhoneStatus, string> = {
  streaming: "En capture",
  stale: "Réseau lent",
  offline: "Hors ligne",
  never_seen: "Jamais connecté",
};

export function statusLabel(status: PhoneStatus): string {
  return STATUS_LABELS[status];
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
  if (!detection.drone) return "Aucun drone";
  const metres = detection.distance_m.toFixed(1).replace(".", ",");
  return `Drone à ${metres} m ± ${Math.round(detection.uncertainty_rel * 100)} %`;
}
