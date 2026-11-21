import { describe, expect, it } from "vitest";
import { phone } from "./fakes";
import { annulusPath, hearsDrone, listening, phoneMarker, rangeRings } from "./mapgeom";
import type { PhoneState } from "./state";

const at = (overrides: Record<string, unknown>) => phone(overrides) as unknown as PhoneState;

describe("rangeRings", () => {
  it("draws one ring per phone hearing the drone: distance, margin, freshness, phone position", () => {
    const rings = rangeRings([
      at({ profile: "noe", position_m: { x: 2, y: 9, z: 0 } }),
      at({ profile: "tristan", detection: null }),
      at({
        profile: "maxence",
        position_m: { x: 2, y: 12, z: 0.8 },
        detection: { drone: true, distance_m: 4, uncertainty_rel: 0.25, age_s: 3, fresh: false },
      }),
      at({
        profile: "x",
        detection: { drone: false, distance_m: null, uncertainty_rel: null, age_s: 0, fresh: true },
      }),
    ]);
    expect(rings).toEqual([
      { profile: "noe", cx: 2, cy: 9, cz: 0, r: 12.3, inner: 12.3 * 0.9, outer: 12.3 * 1.1, fresh: true },
      { profile: "maxence", cx: 2, cy: 12, cz: 0.8, r: 4, inner: 3, outer: 5, fresh: false },
    ]);
  });

  it("never gives a negative inner radius", () => {
    const [ring] = rangeRings([
      at({ detection: { drone: true, distance_m: 2, uncertainty_rel: 1.5, age_s: 0, fresh: true } }),
    ]);
    expect(ring.inner).toBe(0);
  });
});

describe("annulusPath", () => {
  it("draws the outer then the inner circle, to be filled with evenodd", () => {
    expect(annulusPath(5, 6, 1, 2)).toBe(
      "M3 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0ZM4 6a1 1 0 1 0 2 0a1 1 0 1 0 -2 0Z",
    );
  });
});

describe("listening", () => {
  it("tells whether a phone is listening", () => {
    expect(["streaming", "stale", "offline", "never_seen"].map((s) => listening(s as never))).toEqual([
      "on",
      "degraded",
      "off",
      "never",
    ]);
  });
});

describe("hearsDrone", () => {
  const detection = (drone: boolean, fresh: boolean) =>
    drone
      ? { drone, distance_m: 3, uncertainty_rel: 0.1, age_s: 0, fresh }
      : { drone, distance_m: null, uncertainty_rel: null, age_s: 0, fresh };

  it("is true only for a fresh detection of the drone", () => {
    expect(hearsDrone(at({ detection: detection(true, true) }))).toBe(true);
    expect(hearsDrone(at({ detection: detection(true, false) }))).toBe(false);
    expect(hearsDrone(at({ detection: detection(false, true) }))).toBe(false);
    expect(hearsDrone(at({ detection: null }))).toBe(false);
  });
});

describe("phoneMarker", () => {
  it("describes a listening phone hearing the drone, for the map and its tests", () => {
    expect(phoneMarker(at({ profile: "noe", label: "Téléphone de Noé" }))).toEqual({
      label: "Téléphone de Noé : à l'écoute, détecte le drone",
      className: "phone-marker on detecting",
      data: { "data-profile": "noe", "data-listening": "on", "data-detecting": "true" },
    });
  });

  it("describes a silent phone that does not hear the drone", () => {
    expect(phoneMarker(at({ profile: "x", label: "X", status: "offline", detection: null }))).toEqual({
      label: "X : pas à l'écoute",
      className: "phone-marker off",
      data: { "data-profile": "x", "data-listening": "off", "data-detecting": "false" },
    });
  });
});
