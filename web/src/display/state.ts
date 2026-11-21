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

export interface StateMessage {
  readonly type: "state";
  readonly server_time: number;
  readonly estimator: EstimatorName;
  readonly phones: readonly PhoneState[];
  /** Position du drone : toujours null tant que ③ n'est pas branché. */
  readonly drone: null;
}

type Obj = Record<string, unknown>;

const STATUSES: readonly unknown[] = ["streaming", "stale", "offline", "never_seen"];
const ESTIMATORS: readonly unknown[] = ["none", "scripted"];

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
    obj.drone === null &&
    Array.isArray(obj.phones) &&
    obj.phones.every(isPhone);
  return valid ? (obj as unknown as StateMessage) : undefined;
}
