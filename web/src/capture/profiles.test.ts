import { describe, expect, it } from "vitest";
import { findProfile, PROFILES } from "./profiles";

describe("profiles", () => {
  it("lists the five team phones in display order", () => {
    expect(PROFILES.map((p) => p.id)).toEqual(["axel", "maxence", "tristan", "noe", "charlene"]);
  });

  it("parses a select value into its profile", () => {
    expect(findProfile("noe")).toEqual({ id: "noe", label: "Téléphone de Noé" });
  });

  it("returns undefined for the placeholder or an unknown value", () => {
    expect(findProfile("")).toBeUndefined();
    expect(findProfile("bob")).toBeUndefined();
  });
});
