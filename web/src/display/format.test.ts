import { describe, expect, it } from "vitest";
import { droneView, phone } from "./fakes";
import {
  ageText,
  altitudeText,
  detectionText,
  droneStatusText,
  levelText,
  listeningText,
  metres,
  rangeText,
  shortName,
  shortStatus,
  statusLabel,
  trackBadge,
  truthErrorText,
  utcClock,
  zoneText,
} from "./format";
import type { DroneView, PhoneState } from "./state";

describe("statusLabel", () => {
  it("names every phone status in French", () => {
    expect(["streaming", "stale", "offline", "never_seen"].map((s) => statusLabel(s as never))).toEqual([
      "À l'écoute",
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

const drone = (overrides: Record<string, unknown> = {}) => droneView(overrides) as unknown as DroneView;

describe("metres", () => {
  it("uses a French decimal comma and one decimal", () => {
    expect(metres(3.14159)).toBe("3,1 m");
    expect(metres(0)).toBe("0,0 m");
  });
});

describe("droneStatusText", () => {
  it.each([
    [null, "none", "Pas d'estimateur"],
    [null, "scripted", "En attente du premier calcul"],
    [{}, "scripted", "Localisé (3 téléphones)"],
    [{ status: "insufficient", detecting: 1, zone: null }, "scripted", "1 téléphone détecte, 3 nécessaires"],
    [{ status: "insufficient", detecting: 2, zone: null }, "scripted", "2 téléphones détectent, 3 nécessaires"],
    [{ status: "no_detection", detecting: 0, zone: null }, "scripted", "Aucun téléphone ne détecte le drone"],
    [{ status: "inconsistent", zone: null }, "scripted", "Distances incompatibles entre elles"],
  ])("%o (%s) → %s", (overrides, estimator, text) => {
    expect(droneStatusText(overrides === null ? null : drone(overrides), estimator as never)).toBe(text);
  });
});

describe("zone texts", () => {
  const zone = drone().zone!;

  it("gives the position with its radius", () => {
    expect(zoneText(zone)).toBe("x 3,1 m · y 7,9 m · ± 0,8 m");
  });

  it("gives the altitude with its range", () => {
    expect(altitudeText(zone)).toBe("1,4 m (1,1 à 1,7 m)");
  });
});

describe("truthErrorText", () => {
  it("measures the gap between the computed centre and the simulated drone", () => {
    expect(truthErrorText(drone({ zone: { ...drone().zone, x_m: 3.0, y_m: 8.5 } }))).toBe("0,5 m");
  });

  it("is absent without simulation or without position", () => {
    expect(truthErrorText(drone({ truth: null }))).toBeNull();
    expect(truthErrorText(drone({ status: "insufficient", zone: null }))).toBeNull();
  });
});

describe("shortStatus", () => {
  it("names every phone status in one short word for the sensor table", () => {
    expect(["streaming", "stale", "offline", "never_seen"].map((s) => shortStatus(s as never))).toEqual([
      "Écoute",
      "Lent",
      "Hors ligne",
      "Jamais",
    ]);
  });
});

describe("rangeText", () => {
  it("gives the distance and its margin, or why there is none", () => {
    expect(rangeText(null, "none")).toBe("—");
    expect(rangeText(null, "scripted")).toBe("En attente");
    expect(rangeText({ drone: false, distance_m: null, uncertainty_rel: null, age_s: 0, fresh: true }, "scripted")).toBe(
      "Aucun drone",
    );
    expect(rangeText({ drone: true, distance_m: 5.06, uncertainty_rel: 0.1, age_s: 0, fresh: true }, "scripted")).toBe(
      "5,1 m ± 10 %",
    );
  });
});

describe("utcClock", () => {
  it("shows the server time as a 24 h UTC clock", () => {
    expect(utcClock(Date.UTC(2026, 10, 21, 14, 32, 7, 800) / 1000)).toBe("14:32:07Z");
  });
});

describe("shortName", () => {
  it("keeps the first name of the phone label for the map", () => {
    expect(shortName("Téléphone de Noé")).toBe("Noé");
    expect(shortName("Tablette")).toBe("Tablette");
  });
});

describe("listeningText", () => {
  it("counts the phones that are listening right now", () => {
    const phones = [phone(), phone({ status: "stale" }), phone({ status: "offline" })] as PhoneState[];
    expect(listeningText(phones)).toBe("1/3 à l'écoute");
  });
});

describe("trackBadge", () => {
  const drone = (status: string) => droneView({ status, zone: status === "located" ? droneView().zone : null }) as DroneView;
  it.each([
    ["located", "Localisée", "hostile"],
    ["insufficient", "Non localisée", "warn"],
    ["inconsistent", "Incohérente", "warn"],
    ["no_detection", "Aucune détection", "off"],
  ])("%s → %s (%s)", (status, text, tone) => {
    expect(trackBadge(drone(status), "scripted")).toEqual({ text, tone });
  });

  it("says why there is no result yet", () => {
    expect(trackBadge(null, "none")).toEqual({ text: "Pas d'estimateur", tone: "off" });
    expect(trackBadge(null, "scripted")).toEqual({ text: "En attente", tone: "off" });
  });
});
