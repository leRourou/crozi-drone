/** Plan de salle en 3D (React Three Fiber), chargé à la demande : même état, même sélection que le plan 2D. */
import { OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Vector3 } from "three";
import { CAMERA_PRESETS, type CameraPreset, mapMarkers } from "./scene3d";
import { Markers3D } from "./scene/Markers3D";
import { OverlayProjector, Overlays } from "./scene/Overlays3D";
import { Room3D } from "./scene/Room3D";
import { readSceneColors } from "./scene/theme";
import type { Selection } from "./selection";
import type { StateMessage } from "./state";

interface Props {
  state: StateMessage;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}

/** Applique un point de vue : place la caméra, vise le centre de la salle. */
function CameraRig({ preset }: { preset: CameraPreset }) {
  const { camera, controls, invalidate } = useThree();
  useEffect(() => {
    const { position, target } = CAMERA_PRESETS[preset];
    camera.position.set(...position);
    const orbit = controls as { target: Vector3; update: () => void } | null; // OrbitControls makeDefault
    orbit?.target.set(...target);
    orbit?.update();
    invalidate();
  }, [preset, camera, controls, invalidate]);
  return null;
}

export default function Map3D({ state, selected, onSelect }: Props) {
  const [preset, setPreset] = useState<CameraPreset>("iso");
  const elements = useRef(new Map<string, HTMLDivElement>());
  const markers = useMemo(() => mapMarkers(state.phones, state.drone), [state.phones, state.drone]);
  const colors = useMemo(() => readSceneColors(getComputedStyle(document.querySelector("main.display")!)), []);
  return (
    <div className="map3d" role="group" aria-label="Plan de salle en 3D : téléphones et drone">
      <div className="presets" role="toolbar" aria-label="Point de vue">
        {(Object.keys(CAMERA_PRESETS) as CameraPreset[]).map((key) => (
          <button key={key} type="button" aria-pressed={preset === key} onClick={() => setPreset(key)}>
            {CAMERA_PRESETS[key].label}
          </button>
        ))}
      </div>
      <Canvas
        frameloop="demand"
        camera={{ position: CAMERA_PRESETS.iso.position, fov: 45, near: 0.1, far: 200 }}
        onCreated={({ gl }) => {
          gl.localClippingEnabled = true; // sphères de distance découpées par les murs
        }}
      >
        <color attach="background" args={[colors.bg]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[5, 12, 8]} intensity={1.2} />
        <Room3D colors={colors} />
        <Markers3D phones={state.phones} drone={state.drone} colors={colors} />
        <OverlayProjector markers={markers} elements={elements} />
        <OrbitControls makeDefault target={CAMERA_PRESETS.iso.target} maxPolarAngle={Math.PI / 2 - 0.05} minDistance={3} maxDistance={60} />
        <CameraRig preset={preset} />
      </Canvas>
      <Overlays markers={markers} elements={elements} selected={selected} onSelect={onSelect} />
    </div>
  );
}
