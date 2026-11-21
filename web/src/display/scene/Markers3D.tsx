/**
 * Éléments vivants de la scène : sphères de distance, bande d'altitude de la zone et de la piste, fil d'altitude
 * du drone, téléphones. Les marqueurs cliquables sont des surcouches HTML (Overlays3D.tsx).
 */
import { Edges, Line } from "@react-three/drei";
import { useMemo } from "react";
import { DoubleSide, Plane, Vector3 } from "three";
import { hearsDrone, rangeRings, type Ring } from "../mapgeom";
import { ROOM } from "../room";
import { altitudeBand, floorRadius, roomClipPlanes, toThree, velocityArrow, type Vec3 } from "../scene3d";
import type { DroneView, PhoneState, Track, Zone } from "../state";
import type { SceneColors } from "./theme";

const FLOOR_LIFT_M = 0.01;
function DistanceShell({ ring, color, planes }: { ring: Ring; color: string; planes: Plane[] }) {
  const center = toThree({ x: ring.cx, y: ring.cy, z: ring.cz });
  const [inner, outer] = [floorRadius(ring.inner, ring.cz) ?? 0, floorRadius(ring.outer, ring.cz)];
  const fade = ring.fresh ? 1 : 0.35;
  return (
    <group data-ring={ring.profile}>
      <mesh position={center}>
        <sphereGeometry args={[ring.r, 48, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.07 * fade} depthWrite={false} side={DoubleSide} clippingPlanes={planes} />
      </mesh>
      {outer !== null && (
        <mesh position={[center[0], FLOOR_LIFT_M, center[2]]} rotation-x={-Math.PI / 2}>
          <ringGeometry args={[inner, outer, 96]} />
          <meshBasicMaterial color={color} transparent opacity={0.18 * fade} depthWrite={false} side={DoubleSide} clippingPlanes={planes} />
        </mesh>
      )}
    </group>
  );
}

function AltitudeBand({ zone, color, opacity }: { zone: Zone | Track; color: string; opacity: number }) {
  const band = altitudeBand(zone, ROOM.ceiling_m);
  return (
    <mesh position={band.center}>
      <cylinderGeometry args={[band.radius, band.radius, band.height, 48]} />
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
      <Edges color={color} />
    </mesh>
  );
}

function VelocityArrow({ track, color }: { track: Track; color: string }) {
  const arrow = velocityArrow(track);
  if (arrow === null) return null;
  return (
    <arrowHelper
      args={[new Vector3(...arrow.direction), new Vector3(...arrow.origin), arrow.length, color, 0.25, 0.15]}
    />
  );
}

/** Fil pointillé du drone jusqu'au sol : lecture de l'altitude. */
function AltitudeWire({ at }: { at: { x_m: number; y_m: number; z_m: number } }) {
  const top = toThree({ x: at.x_m, y: at.y_m, z: at.z_m });
  const foot: Vec3 = [top[0], 0, top[2]];
  return <Line points={[top, foot]} color="#9fb4c8" dashed dashSize={0.1} gapSize={0.08} lineWidth={1} />;
}

interface Props {
  phones: readonly PhoneState[];
  drone: DroneView | null;
  colors: SceneColors;
}

export function Markers3D({ phones, drone, colors }: Props) {
  const planes = useMemo(
    () => roomClipPlanes(ROOM).map(({ normal, constant }) => new Plane(new Vector3(...normal), constant)),
    [],
  );
  const shown = drone?.track ?? drone?.zone; // la piste filtrée si elle existe, sinon la zone brute
  return (
    <group>
      {rangeRings(phones).map((ring) => (
        <DistanceShell key={ring.profile} ring={ring} color={colors.phone} planes={planes} />
      ))}
      {drone?.zone && <AltitudeBand zone={drone.zone} color={colors.drone} opacity={drone.track ? 0.05 : 0.15} />}
      {drone?.track && <AltitudeBand zone={drone.track} color={colors.drone} opacity={0.2} />}
      {drone?.track && <VelocityArrow track={drone.track} color={colors.drone} />}
      {drone?.truth && <AltitudeWire at={drone.truth} />}
      {shown && <AltitudeWire at={shown} />}
      {phones.map((phone) => (
        <mesh key={phone.profile} position={toThree({ ...phone.position_m, z: phone.position_m.z + 0.04 })}>
          <boxGeometry args={[0.16, 0.08, 0.3]} />
          <meshStandardMaterial color={hearsDrone(phone) ? colors.phoneDetecting : colors.phone} />
        </mesh>
      ))}
    </group>
  );
}
