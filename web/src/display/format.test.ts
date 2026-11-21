import { describe, expect, it } from "vitest";
import { ageText, detectionText, levelText, statusLabel } from "./format";

describe("statusLabel", () => {
  it("names every phone status in French", () => {
    expect(["streaming", "stale", "offline", "never_seen"].map((s) => statusLabel(s as never))).toEqual([
      "En capture",
      "Réseau lent",
      "Hors ligne",
      "Jamais connecté",
    ]);
  });
});

describe("ageText", () => {
  it.each([
    [null, "—"],
    [0.4, "à l'instant"],
    [0.99, "à l'instant"],
    [1, "il y a 1 s"],
    [59.4, "il y a 59 s"],
    [60, "il y a 1 min"],
    [185, "il y a 3 min"],
  ])("%s s → %s", (age, text) => {
    expect(ageText(age)).toBe(text);
  });
});

describe("levelText", () => {
  it("shows the RMS level, digital silence, or nothing before the first stats", () => {
    expect(levelText(-42.06)).toBe("-42 dBFS");
    expect(levelText(null)).toBe("—");
  });
});

describe("detectionText", () => {
  it("says there is no estimator when the server runs without one", () => {
    expect(detectionText(null, "none")).toBe("Pas d'estimateur");
  });

  it("waits for the first window when an estimator runs", () => {
    expect(detectionText(null, "scripted")).toBe("En attente de son");
  });

  it("reports no drone", () => {
    expect(
      detectionText({ drone: false, distance_m: null, uncertainty_rel: null, age_s: 0, fresh: true }, "scripted"),
    ).toBe("Aucun drone");
  });

  it("reports the distance with its uncertainty, French decimal comma", () => {
    expect(
      detectionText({ drone: true, distance_m: 12.34, uncertainty_rel: 0.1, age_s: 0, fresh: true }, "scripted"),
    ).toBe("Drone à 12,3 m ± 10 %");
  });
});
