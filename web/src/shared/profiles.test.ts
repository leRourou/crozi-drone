import { describe, expect, it } from "vitest";
import { findProfile, PROFILES } from "./profiles";

describe("profiles", () => {
  it("lists the three team phones of the shared contract, in display order, with positions in metres", () => {
    expect(PROFILES).toEqual([
      { id: "noe", label: "Téléphone de Noé", position_m: { x: 2.06, y: 9.66, z: 0 } },
      { id: "tristan", label: "Téléphone de Tristan", position_m: { x: 4, y: 10.76, z: 0 } },
      { id: "maxence", label: "Téléphone de Maxence", position_m: { x: 2.06, y: 11.86, z: 0 } },
    ]);
  });

  it("parses a select value into its profile", () => {
    expect(findProfile("noe")?.label).toBe("Téléphone de Noé");
  });

  it("returns undefined for the placeholder, an unknown or a removed value", () => {
    expect(findProfile("")).toBeUndefined();
    expect(findProfile("bob")).toBeUndefined();
    expect(findProfile("axel")).toBeUndefined();
    expect(findProfile("charlene")).toBeUndefined();
  });
});
