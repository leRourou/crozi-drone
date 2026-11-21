/** Salle en 3D : sol au contour exact, grille 1 m, murs translucides, piliers. */
import { Edges } from "@react-three/drei";
import { useMemo } from "react";
import { BufferGeometry, DoubleSide, Float32BufferAttribute, Shape, Vector2 } from "three";
import { ROOM } from "../room";
import { toThree, wallSegments } from "../scene3d";
import type { SceneColors } from "./theme";

const WALL_THICKNESS_M = 0.1;
const LIFT_M = 0.005; // décolle la grille du sol (pas de z-fighting)

function gridGeometry() {
  const points: number[] = [];
  const line = (a: [number, number], b: [number, number]) =>
    points.push(...toThree({ x: a[0], y: a[1], z: LIFT_M }), ...toThree({ x: b[0], y: b[1], z: LIFT_M }));
  for (let x = 1; x < ROOM.width_m; x += 1) line([x, 0], [x, ROOM.height_m]);
  for (let y = 1; y < ROOM.height_m; y += 1) line([0, y], [ROOM.width_m, y]);
  return new BufferGeometry().setAttribute("position", new Float32BufferAttribute(points, 3));
}

export function Room3D({ colors }: { colors: SceneColors }) {
  // Le contour est dessiné dans le plan (x, y) puis couché : rotation +90° autour de x, (x, y, 0) → (x, 0, y).
  const floor = useMemo(() => new Shape(ROOM.outline.map(([x, y]) => new Vector2(x, y))), []);
  const grid = useMemo(gridGeometry, []);
  const walls = useMemo(() => wallSegments(ROOM.outline, ROOM.ceiling_m), []);
  return (
    <group>
      <mesh rotation-x={Math.PI / 2}>
        <shapeGeometry args={[floor]} />
        <meshStandardMaterial color={colors.floor} side={DoubleSide} />
      </mesh>
      <lineSegments geometry={grid}>
        <lineBasicMaterial color={colors.grid} />
      </lineSegments>
      {walls.map((w) => (
        <mesh key={w.center.join()} position={w.center} rotation-y={w.angle}>
          <boxGeometry args={[w.length, w.height, WALL_THICKNESS_M]} />
          <meshStandardMaterial color={colors.wall} transparent opacity={0.1} depthWrite={false} />
          <Edges color={colors.wall} />
        </mesh>
      ))}
      {ROOM.pillars.map((p) => (
        <mesh key={p.y} position={toThree({ x: p.x + p.w / 2, y: p.y + p.h / 2, z: ROOM.ceiling_m / 2 })}>
          <boxGeometry args={[p.w, ROOM.ceiling_m, p.h]} />
          <meshStandardMaterial color="#3a4433" />
          <Edges color={colors.wall} />
        </mesh>
      ))}
    </group>
  );
}
