/**
 * Géométrie de la vue 3D, sans WebGL (testée en node). Repère de la salle : x vers l'est, y vers le sud,
 * z vers le haut ; repère three : y vers le haut. `toThree` est la seule conversion entre les deux.
 */
import type { Camera } from "three";
import { Vector3 } from "three";
import { phoneMarker } from "./mapgeom";
import { ROOM } from "./room";
import type { Selection } from "./selection";
import type { DroneView, PhoneState, Track, Zone } from "./state";

export type Vec3 = [number, number, number]; // forme attendue par les props position de R3F

/** Salle (x, y, z) → three (x, z, y) : est × haut = sud, donc ni miroir ni rotation. */
export function toThree(p: { readonly x: number; readonly y: number; readonly z: number }): Vec3 {
  return [p.x, p.z, p.y];
}

/** Mur posé au sol : box de longueur `length` sur son x local, tournée de `angle` autour de y three. */
export interface Wall {
  readonly center: Vec3;
  readonly length: number;
  readonly angle: number;
  readonly height: number;
}

/** Un mur par côté du contour fermé (repère de la salle, en mètres). */
export function wallSegments(outline: readonly (readonly [number, number])[], height: number): Wall[] {
  return outline.map(([x0, y0], i) => {
    const [x1, y1] = outline[(i + 1) % outline.length];
    const [dx, dy] = [x1 - x0, y1 - y0];
    return {
      center: toThree({ x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: height / 2 }),
      length: Math.hypot(dx, dy),
      angle: Math.atan2(-dy, dx), // le x local tourné de angle autour de y three donne (cos, 0, -sin)
      height,
    };
  });
}

/** Plans three (normale, constante) qui gardent l'intérieur de la boîte de la salle, sol à plafond. */
export function roomClipPlanes(room: { width_m: number; height_m: number; ceiling_m: number }) {
  const { width_m: w, height_m: h, ceiling_m: c } = room;
  const planes: { normal: Vec3; constant: number }[] = [
    { normal: [1, 0, 0], constant: 0 },
    { normal: [-1, 0, 0], constant: w },
    { normal: [0, 1, 0], constant: 0 },
    { normal: [0, -1, 0], constant: c },
    { normal: [0, 0, 1], constant: 0 },
    { normal: [0, 0, -1], constant: h },
  ];
  return planes;
}

/** Rayon du cercle où une sphère de distance (centre à la hauteur cz) coupe le sol ; null si elle ne l'atteint pas. */
export function floorRadius(r: number, cz: number): number | null {
  return Math.abs(cz) > r ? null : Math.sqrt(r * r - cz * cz);
}

const MIN_BAND_M = 0.02; // épaisseur minimale pour qu'une bande plate reste visible

/** Cylindre vertical sur le disque (x, y, rayon), de z_min à z_max, borné entre sol et plafond. */
export function altitudeBand(
  zone: Pick<Zone, "x_m" | "y_m" | "radius_m" | "z_min_m" | "z_max_m">,
  ceiling: number,
): { center: Vec3; radius: number; height: number } {
  const clamp = (z: number) => Math.min(ceiling, Math.max(0, z));
  const [lo, hi] = [clamp(zone.z_min_m), clamp(zone.z_max_m)];
  return {
    center: toThree({ x: zone.x_m, y: zone.y_m, z: (lo + hi) / 2 }),
    radius: zone.radius_m,
    height: Math.max(MIN_BAND_M, hi - lo),
  };
}

const STILL_MPS = 0.05; // en dessous, la piste est considérée immobile : pas de flèche

/** Flèche de vitesse de la piste : de sa position à celle prévue dans une seconde ; null si immobile. */
export function velocityArrow(track: Pick<Track, "x_m" | "y_m" | "z_m" | "vx_mps" | "vy_mps">) {
  const speed = Math.hypot(track.vx_mps, track.vy_mps);
  if (speed < STILL_MPS) return null;
  return {
    origin: toThree({ x: track.x_m, y: track.y_m, z: track.z_m }),
    direction: toThree({ x: track.vx_mps / speed, y: track.vy_mps / speed, z: 0 }),
    length: speed,
  };
}

export type CameraPreset = "top" | "iso" | "side";

const CENTER = toThree({ x: ROOM.width_m / 2, y: ROOM.height_m / 2, z: 0 });

/** Points de vue proposés ; « dessus » est décalé d'un cheveu vers le sud pour garder le nord en haut. */
export const CAMERA_PRESETS: Record<CameraPreset, { position: Vec3; target: Vec3; label: string }> = {
  top: { position: toThree({ x: ROOM.width_m / 2, y: ROOM.height_m / 2 + 0.01, z: 28 }), target: CENTER, label: "Dessus" },
  iso: { position: toThree({ x: ROOM.width_m + 12, y: ROOM.height_m + 10, z: 18 }), target: CENTER, label: "Iso" },
  side: { position: toThree({ x: ROOM.width_m + 22, y: ROOM.height_m / 2, z: 2 }), target: CENTER, label: "Côté" },
};

/** Marqueur cliquable de la vue 3D, dessiné en HTML par-dessus le canvas à la projection de `position`. */
export interface MapMarker {
  readonly key: string;
  readonly position: Vec3;
  readonly label: string;
  readonly className: string;
  readonly data: Readonly<Record<string, string>>;
  readonly select: Exclude<Selection, null>;
  readonly glyph: "phone" | "drone" | "ghost";
}

const LABEL_ABOVE_PHONE_M = 0.35;

const at = (p: { x_m: number; y_m: number; z_m: number }) => toThree({ x: p.x_m, y: p.y_m, z: p.z_m });

function droneMarkers(drone: DroneView | null): MapMarker[] {
  if (drone === null) return [];
  const markers: MapMarker[] = [];
  const select = { kind: "drone" } as const;
  if (drone.truth) {
    markers.push({ key: "truth", position: at(drone.truth), label: "Drone simulé (position vraie)", className: "drone-marker ghost", data: {}, select, glyph: "ghost" });
  }
  const shown = drone.track ?? drone.zone; // la piste filtrée si elle existe, sinon la zone brute
  if (shown) {
    const data = { "data-drone": drone.track ? "tracked" : "located" };
    markers.push({ key: "drone", position: at(shown), label: "Drone (position calculée)", className: "drone-marker", data, select, glyph: "drone" });
  }
  return markers;
}

/** Marqueurs dans l'ordre d'empilement : drones d'abord, téléphones par-dessus (même règle que le plan 2D). */
export function mapMarkers(phones: readonly PhoneState[], drone: DroneView | null): MapMarker[] {
  const phoneMarkers = phones.map((phone): MapMarker => {
    const [x, y, z] = toThree(phone.position_m);
    return {
      key: `phone:${phone.profile}`,
      position: [x, y + LABEL_ABOVE_PHONE_M, z],
      ...phoneMarker(phone),
      select: { kind: "phone", profile: phone.profile },
      glyph: "phone",
    };
  });
  return [...droneMarkers(drone), ...phoneMarkers];
}

/** Pixel (origine en haut à gauche) où `position` est dessiné ; invisible derrière la caméra ou hors profondeur. */
export function projectToScreen(position: Vec3, camera: Camera, size: { width: number; height: number }) {
  const ndc = new Vector3(...position).project(camera);
  return {
    x: ((ndc.x + 1) / 2) * size.width,
    y: ((1 - ndc.y) / 2) * size.height,
    visible: ndc.z > -1 && ndc.z < 1,
  };
}
