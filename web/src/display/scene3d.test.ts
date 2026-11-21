import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Plane, Vector3 } from "three";
import { droneView, phone } from "./fakes";
import type { DroneView, PhoneState } from "./state";
import {
  altitudeBand, CAMERA_PRESETS, floorRadius, mapMarkers, projectToScreen, roomClipPlanes, toThree, velocityArrow, wallSegments,
} from "./scene3d";

const close = (actual: readonly number[], expected: readonly number[]) =>
  actual.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 9));

describe("toThree", () => {
  it("maps the room frame (x east, y south, z up) to three (x, y up, z)", () => {
    expect(toThree({ x: 1, y: 2, z: 3 })).toEqual([1, 3, 2]);
  });

  it("keeps the handedness: east × up = south, so nothing is mirrored", () => {
    const east = new Vector3(...toThree({ x: 1, y: 0, z: 0 }));
    const up = new Vector3(...toThree({ x: 0, y: 0, z: 1 }));
    expect(east.cross(up).toArray()).toEqual(toThree({ x: 0, y: 1, z: 0 }));
  });
});

describe("wallSegments", () => {
  // Une box de longueur `length` sur son x local, tournée de `angle` autour de y, posée sur `center`.
  const ends = (w: ReturnType<typeof wallSegments>[number]) => {
    const half = new Vector3(w.length / 2, 0, 0).applyAxisAngle(new Vector3(0, 1, 0), w.angle);
    const c = new Vector3(...w.center);
    return [c.clone().sub(half).toArray(), c.clone().add(half).toArray()];
  };

  it("draws one wall per side of the closed outline, standing on the floor", () => {
    const walls = wallSegments([[0, 0], [4, 0], [4, 3]], 2.5);
    expect(walls).toHaveLength(3);
    walls.forEach((w) => expect(w.height).toBe(2.5));
    expect(walls.map((w) => w.length)).toEqual([4, 3, 5]);
  });

  it("puts each wall between its two corners", () => {
    const walls = wallSegments([[0, 0], [4, 0], [4, 3]], 2);
    close(ends(walls[0]).flat(), [0, 1, 0, 4, 1, 0]);
    close(ends(walls[1]).flat(), [4, 1, 0, 4, 1, 3]);
    close(ends(walls[2]).flat(), [4, 1, 3, 0, 1, 0]);
  });
});

describe("roomClipPlanes", () => {
  const planes = roomClipPlanes({ width_m: 10, height_m: 20, ceiling_m: 3 }).map(
    ({ normal, constant }) => new Plane(new Vector3(...normal), constant),
  );
  const kept = (p: [number, number, number]) => planes.every((pl) => pl.distanceToPoint(new Vector3(...p)) >= 0);

  it("keeps what is inside the room, floor to ceiling", () => {
    expect(kept(toThree({ x: 0, y: 0, z: 0 }))).toBe(true);
    expect(kept(toThree({ x: 10, y: 20, z: 3 }))).toBe(true);
  });

  it("cuts what is outside, on every side", () => {
    const outside = [
      { x: -0.1, y: 5, z: 1 }, { x: 10.1, y: 5, z: 1 }, { x: 5, y: -0.1, z: 1 },
      { x: 5, y: 20.1, z: 1 }, { x: 5, y: 5, z: -0.1 }, { x: 5, y: 5, z: 3.1 },
    ];
    expect(outside.map((p) => kept(toThree(p)))).toEqual([false, false, false, false, false, false]);
  });
});

describe("floorRadius", () => {
  it("is the radius of the circle where a distance sphere meets the floor", () => {
    expect(floorRadius(5, 0)).toBe(5);
    expect(floorRadius(5, 3)).toBe(4);
  });

  it("is a point when the sphere just touches the floor", () => {
    expect(floorRadius(3, 3)).toBe(0);
  });

  it("is null when the sphere does not reach the floor", () => {
    expect(floorRadius(2, 3)).toBeNull();
  });
});

describe("altitudeBand", () => {
  const disc = { x_m: 3, y_m: 8, radius_m: 0.5 };

  it("is a vertical cylinder over the disc, from the lowest to the highest altitude", () => {
    expect(altitudeBand({ ...disc, z_min_m: 1, z_max_m: 2 }, 3)).toEqual({ center: [3, 1.5, 8], radius: 0.5, height: 1 });
  });

  it("stays between floor and ceiling", () => {
    expect(altitudeBand({ ...disc, z_min_m: -1, z_max_m: 5 }, 3)).toEqual({ center: [3, 1.5, 8], radius: 0.5, height: 3 });
  });

  it("keeps a visible thickness when the band is flat or out of the room", () => {
    expect(altitudeBand({ ...disc, z_min_m: 4, z_max_m: 5 }, 3).height).toBe(0.02);
  });
});

describe("velocityArrow", () => {
  it("points where the drone will be in one second", () => {
    const arrow = velocityArrow({ x_m: 1, y_m: 2, z_m: 1.5, vx_mps: 3, vy_mps: -4 });
    expect(arrow?.origin).toEqual([1, 1.5, 2]);
    close(arrow!.direction, [0.6, 0, -0.8]);
    expect(arrow?.length).toBeCloseTo(5, 9);
  });

  it("starts at 5 cm/s", () => {
    expect(velocityArrow({ x_m: 1, y_m: 2, z_m: 1, vx_mps: 0.05, vy_mps: 0 })?.length).toBe(0.05);
  });

  it("is null when the drone (almost) does not move", () => {
    expect(velocityArrow({ x_m: 1, y_m: 2, z_m: 1, vx_mps: 0.01, vy_mps: 0.02 })).toBeNull();
  });
});

describe("CAMERA_PRESETS", () => {
  it("all look at the middle of the room, the top view from straight above", () => {
    const targets = new Set(Object.values(CAMERA_PRESETS).map((p) => p.target.join()));
    expect(targets.size).toBe(1);
    const { position, target } = CAMERA_PRESETS.top;
    expect(position[1]).toBeGreaterThan(20);
    expect(Math.hypot(position[0] - target[0], position[2] - target[2])).toBeLessThan(0.1);
  });
});

describe("mapMarkers", () => {
  const phones = [
    phone({ profile: "noe", label: "Téléphone de Noé", position_m: { x: 2, y: 9, z: 0 } }),
    phone({ profile: "x", label: "X", status: "offline", detection: null, position_m: { x: 4, y: 1, z: 1 } }),
  ] as unknown as PhoneState[];

  it("lists the clickable markers: drones first, phones last so they stay on top", () => {
    const drone = droneView() as unknown as DroneView;
    expect(mapMarkers(phones, drone).map((m) => [m.key, m.glyph, m.select])).toEqual([
      ["truth", "ghost", { kind: "drone" }],
      ["drone", "drone", { kind: "drone" }],
      ["phone:noe", "phone", { kind: "phone", profile: "noe" }],
      ["phone:x", "phone", { kind: "phone", profile: "x" }],
    ]);
  });

  it("puts each drone at its altitude and each phone label just above the phone", () => {
    const drone = droneView() as unknown as DroneView;
    const at = Object.fromEntries(mapMarkers(phones, drone).map((m) => [m.key, m.position]));
    expect(at.truth).toEqual([3, 1.5, 8]);
    expect(at.drone).toEqual([3, 1.5, 8.1]); // la piste
    expect(at["phone:noe"]).toEqual([2, 0.35, 9]);
    expect(at["phone:x"]).toEqual([4, 1.35, 1]);
  });

  it("keeps the 2D names and attributes, and tells a tracked from a located drone", () => {
    const located = droneView({ track: null, truth: null }) as unknown as DroneView;
    const [drone, noe] = mapMarkers(phones, located);
    expect(drone).toMatchObject({ label: "Drone (position calculée)", className: "drone-marker", data: { "data-drone": "located" } });
    expect(drone.position).toEqual([3.1, 1.4, 7.9]); // la zone brute
    expect(noe).toMatchObject({ label: "Téléphone de Noé : à l'écoute, détecte le drone", className: "phone-marker on detecting" });
    expect(mapMarkers(phones, droneView() as unknown as DroneView)[1].data).toEqual({ "data-drone": "tracked" });
  });

  it("has only phones without a drone position", () => {
    expect(mapMarkers(phones, null).map((m) => m.key)).toEqual(["phone:noe", "phone:x"]);
    const lost = droneView({ status: "insufficient", zone: null, track: null, truth: null }) as unknown as DroneView;
    expect(mapMarkers(phones, lost).map((m) => m.key)).toEqual(["phone:noe", "phone:x"]);
  });
});

describe("projectToScreen", () => {
  const camera = new PerspectiveCamera(90, 2, 0.1, 100);
  camera.position.set(0, 0, 10);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const size = { width: 800, height: 400 };

  it("gives the pixel where a point of the scene is drawn", () => {
    expect(projectToScreen([0, 0, 0], camera, size)).toEqual({ x: 400, y: 200, visible: true });
    const up = projectToScreen([0, 5, 0], camera, size); // tan(45°) × 10 = 10 : mi-hauteur au-dessus du centre
    expect(up.x).toBeCloseTo(400, 6);
    expect(up.y).toBeCloseTo(100, 6);
  });

  it("shows what is just past the near plane", () => {
    expect(projectToScreen([0, 0, 9.85], camera, size).visible).toBe(true);
  });

  it("hides what is behind the camera", () => {
    expect(projectToScreen([0, 0, 20], camera, size).visible).toBe(false);
  });
});
