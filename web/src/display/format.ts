/** Textes affichés par la page d'état (aucun calcul de domaine : tout vient du serveur). */
import type { Detection, DroneView, EstimatorName, PhoneStatus, Point3, Zone } from "./state";

type Disc = Pick<Zone, "x_m" | "y_m" | "radius_m">;
type Altitude = Pick<Zone, "z_m" | "z_min_m" | "z_max_m">;
type Planar = Pick<Zone, "x_m" | "y_m">;

const STATUS_LABELS: Record<PhoneStatus, string> = {
  streaming: "À l'écoute",
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

/** Zone brute ou piste filtrée : centre et rayon. */
export function zoneText(zone: Disc): string {
  return `x ${metres(zone.x_m)} · y ${metres(zone.y_m)} · ± ${metres(zone.radius_m)}`;
}

export function altitudeText(zone: Altitude): string {
  return `${metres(zone.z_m)} (${metres(zone.z_min_m).slice(0, -2)} à ${metres(zone.z_max_m)})`;
}

/** Vitesse horizontale de la piste. */
export function speedText(track: { readonly vx_mps: number; readonly vy_mps: number }): string {
  return `${Math.hypot(track.vx_mps, track.vy_mps).toFixed(1).replace(".", ",")} m/s`;
}

/** Écart horizontal entre une position calculée et le drone simulé ; null hors simulation ou sans position. */
export function truthErrorText(truth: Point3 | null, at: Planar | null): string | null {
  if (truth === null || at === null) return null;
  return metres(Math.hypot(at.x_m - truth.x_m, at.y_m - truth.y_m));
}
