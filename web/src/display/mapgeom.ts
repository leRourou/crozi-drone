/** Géométrie de la carte, en mètres dans le repère de la salle (x vers l'est, y vers le sud). */
import type { PhoneState, PhoneStatus } from "./state";

/** Cercle de distance d'un téléphone qui entend le drone, avec sa marge (± incertitude). */
export interface Ring {
  readonly profile: string;
  readonly cx: number;
  readonly cy: number;
  readonly r: number;
  readonly inner: number;
  readonly outer: number;
  readonly fresh: boolean;
}

export function rangeRings(phones: readonly PhoneState[]): Ring[] {
  return phones.flatMap(({ profile, position_m, detection }) => {
    if (!detection?.drone) return [];
    const { distance_m: r, uncertainty_rel: u, fresh } = detection;
    const ring = { profile, cx: position_m.x, cy: position_m.y, r };
    return [{ ...ring, inner: Math.max(0, r * (1 - u)), outer: r * (1 + u), fresh }];
  });
}

/** Anneau entre deux cercles concentriques (à remplir avec fill-rule="evenodd"). */
export function annulusPath(cx: number, cy: number, inner: number, outer: number): string {
  const circle = (r: number) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
  return circle(outer) + circle(inner);
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
