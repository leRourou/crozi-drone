/**
 * Message `state` de /ws/state (docs/protocol.md), validé une fois à l'arrivée.
 * Le serveur est la seule source de vérité : la page affiche, elle ne recalcule rien.
 */

export type PhoneStatus = "streaming" | "stale" | "offline" | "never_seen";
export type EstimatorName = "none" | "scripted";

interface Freshness {
  readonly age_s: number;
  readonly fresh: boolean;
}

/** Une distance n'existe que si un drone est détecté. */
export type Detection =
  | (Freshness & { readonly drone: true; readonly distance_m: number; readonly uncertainty_rel: number })
  | (Freshness & { readonly drone: false; readonly distance_m: null; readonly uncertainty_rel: null });

export interface PhoneState {
  readonly profile: string;
  readonly label: string;
  readonly position_m: { readonly x: number; readonly y: number; readonly z: number };
  readonly status: PhoneStatus;
  readonly session_id: string | null;
  readonly contract: string | null;
  readonly last_seen_age_s: number | null;
  readonly rt_ratio: number | null;
  readonly rms_dbfs: number | null;
  readonly detection: Detection | null;
}

export type DroneStatus = "located" | "insufficient" | "no_detection" | "inconsistent";

/** Zone où se trouve le drone (③), repère de la salle en mètres : x vers l'est, y vers le sud. */
export interface Zone {
  readonly x_m: number;
  readonly y_m: number;
  readonly radius_m: number;
  readonly z_m: number;
  readonly z_min_m: number;
  readonly z_max_m: number;
  readonly tolerance: number;
  readonly degraded: boolean;
}

/** Piste du drone (③, filtre de Kalman) : position lissée, vitesse horizontale, disque à 2 σ. */
export interface Track {
  readonly x_m: number;
  readonly y_m: number;
  readonly z_m: number;
  readonly vx_mps: number;
  readonly vy_mps: number;
  readonly radius_m: number;
  readonly z_min_m: number;
  readonly z_max_m: number;
}

export interface Point3 {
  readonly x_m: number;
  readonly y_m: number;
  readonly z_m: number;
}

interface DroneBase {
  /** Téléphones dont les détections récentes ont été combinées. */
  readonly detecting: number;
  readonly age_s: number;
  /** Piste filtrée, indépendante du statut (peut exister avec 1 ou 2 téléphones) ; null sans piste. */
  readonly track: Track | null;
  /** Position vraie du drone simulé (DISTANCE_ESTIMATOR=scripted) ; null sinon. */
  readonly truth: Point3 | null;
}

/** Une zone n'existe que si le drone est localisé. */
export type DroneView =
  | (DroneBase & { readonly status: "located"; readonly zone: Zone })
  | (DroneBase & { readonly status: Exclude<DroneStatus, "located">; readonly zone: null });

export interface StateMessage {
  readonly type: "state";
  readonly server_time: number;
  readonly estimator: EstimatorName;
  readonly phones: readonly PhoneState[];
  /** Résultat de ③ ; null sans estimateur ou avant le premier calcul. */
  readonly drone: DroneView | null;
}

type Obj = Record<string, unknown>;

const STATUSES: readonly unknown[] = ["streaming", "stale", "offline", "never_seen"];
const ESTIMATORS: readonly unknown[] = ["none", "scripted"];
const DRONE_STATUSES: readonly unknown[] = ["located", "insufficient", "no_detection", "inconsistent"];
const ZONE_NUMBERS = ["x_m", "y_m", "radius_m", "z_m", "z_min_m", "z_max_m", "tolerance"] as const;
const TRACK_NUMBERS = ["x_m", "y_m", "z_m", "vx_mps", "vy_mps", "radius_m", "z_min_m", "z_max_m"] as const;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number"; // JSON n'a ni NaN ni Infinity
const isNumOrNull = (v: unknown) => v === null || isNum(v);
const isStrOrNull = (v: unknown) => v === null || typeof v === "string";

function isDetection(d: unknown): boolean {
  if (d === null) return true;
  if (!isObj(d) || !isNum(d.age_s) || typeof d.fresh !== "boolean") return false;
  if (d.drone === true) return isNum(d.distance_m) && isNum(d.uncertainty_rel);
  return d.drone === false && d.distance_m === null && d.uncertainty_rel === null;
}

function isZone(z: unknown): boolean {
  return isObj(z) && ZONE_NUMBERS.every((k) => isNum(z[k])) && typeof z.degraded === "boolean";
}

function isTrack(t: unknown): boolean {
  return t === null || (isObj(t) && TRACK_NUMBERS.every((k) => isNum(t[k])));
}

function isPoint3(p: unknown): boolean {
  return isObj(p) && isNum(p.x_m) && isNum(p.y_m) && isNum(p.z_m);
}

const isDroneHeader = (d: Obj) => DRONE_STATUSES.includes(d.status) && isNum(d.detecting) && isNum(d.age_s);

const isDronePositions = (d: Obj) => (d.truth === null || isPoint3(d.truth)) && isTrack(d.track);

function isDroneView(d: unknown): boolean {
  if (d === null) return true;
  if (!isObj(d) || !isDroneHeader(d) || !isDronePositions(d)) return false;
  return d.status === "located" ? isZone(d.zone) : d.zone === null;
}

function isPosition(p: unknown): boolean {
  return isObj(p) && isNum(p.x) && isNum(p.y) && isNum(p.z);
}

const isIdentity = (p: Obj) => typeof p.profile === "string" && typeof p.label === "string" && isPosition(p.position_m);

const isSession = (p: Obj) =>
  STATUSES.includes(p.status) && isStrOrNull(p.session_id) && isStrOrNull(p.contract) && isNumOrNull(p.last_seen_age_s);

const isReception = (p: Obj) => isNumOrNull(p.rt_ratio) && isNumOrNull(p.rms_dbfs) && isDetection(p.detection);

function isPhone(p: unknown): boolean {
  return isObj(p) && isIdentity(p) && isSession(p) && isReception(p);
}

/** Texte reçu → message d'état, ou undefined s'il ne respecte pas le protocole. */
export function parseState(text: string): StateMessage | undefined {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch {
    return undefined;
  }
  const valid =
    isObj(obj) &&
    obj.type === "state" &&
    isNum(obj.server_time) &&
    ESTIMATORS.includes(obj.estimator) &&
    isDroneView(obj.drone) &&
    Array.isArray(obj.phones) &&
    obj.phones.every(isPhone);
  return valid ? (obj as unknown as StateMessage) : undefined;
}
