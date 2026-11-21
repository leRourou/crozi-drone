/** Géométrie de la carte, en mètres dans le repère de la salle (x vers l'est, y vers le sud). */
import type { PhoneState, PhoneStatus } from "./state";

/** Cercle de distance d'un téléphone qui entend le drone, avec sa marge (± incertitude). */
export interface Ring {
  readonly profile: string;
  readonly cx: number;
  readonly cy: number;
  /** Hauteur du téléphone : centre de la sphère de distance en 3D. */
  readonly cz: number;
  readonly r: number;
  readonly inner: number;
  readonly outer: number;
  readonly fresh: boolean;
}

export function rangeRings(phones: readonly PhoneState[]): Ring[] {
  return phones.flatMap(({ profile, position_m, detection }) => {
    if (!detection?.drone) return [];
    const { distance_m: r, uncertainty_rel: u, fresh } = detection;
    const ring = { profile, cx: position_m.x, cy: position_m.y, cz: position_m.z, r };
    return [{ ...ring, inner: Math.max(0, r * (1 - u)), outer: r * (1 + u), fresh }];
  });
}

/** Anneau entre deux cercles concentriques (à remplir avec fill-rule="evenodd"). */
export function annulusPath(cx: number, cy: number, inner: number, outer: number): string {
  const circle = (r: number) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
  return circle(outer) + circle(inner);
}

/** Le téléphone entend le drone en ce moment : détection du drone, et récente. */
export function hearsDrone(phone: PhoneState): boolean {
  return phone.detection?.drone === true && phone.detection.fresh;
}

export type Listening = "on" | "degraded" | "off" | "never";

const LISTENING: Record<PhoneStatus, Listening> = {
  streaming: "on",
  stale: "degraded",
  offline: "off",
  never_seen: "never",
};

/** Indicateur d'écoute d'un téléphone. */
export function listening(status: PhoneStatus): Listening {
  return LISTENING[status];
}

/** Marqueur d'un téléphone sur le plan (2D ou 3D) : nom accessible, classes et attributs lus par les tests e2e. */
export function phoneMarker(phone: PhoneState) {
  const state = listening(phone.status);
  const detecting = hearsDrone(phone);
  return {
    label: `${phone.label} : ${phone.status === "streaming" ? "à l'écoute" : "pas à l'écoute"}${detecting ? ", détecte le drone" : ""}`,
    className: `phone-marker ${state}${detecting ? " detecting" : ""}`,
    data: { "data-profile": phone.profile, "data-listening": state, "data-detecting": String(detecting) },
  };
}
