import { describe, expect, it } from "vitest";
import { droneView, message, phone } from "./fakes";
import { parseState } from "./state";

const raw = (obj: unknown) => JSON.stringify(obj);

describe("parseState", () => {
  it("parses a valid state message as sent by the server", () => {
    expect(parseState(raw(message()))).toEqual(message());
  });

  it("accepts a phone out of session (nulls) and a detection without drone", () => {
    const offline = phone({
      status: "offline",
      session_id: null,
      contract: null,
      rt_ratio: null,
      rms_dbfs: null,
      detection: null,
    });
    const noDrone = phone({
      detection: { drone: false, distance_m: null, uncertainty_rel: null, age_s: 1, fresh: true },
    });
    expect(parseState(raw(message({ phones: [offline, noDrone] })))?.phones).toEqual([offline, noDrone]);
  });

  it("parses the drone view: located with a zone, or another status without", () => {
    expect(parseState(raw(message({ drone: droneView() }))) ?.drone).toEqual(droneView());
    const waiting = droneView({ status: "insufficient", detecting: 2, zone: null, truth: null });
    expect(parseState(raw(message({ drone: waiting })))?.drone).toEqual(waiting);
  });

  it.each([
    ["not JSON", "{"],
    ["another message type", raw(message({ type: "stats" }))],
    ["an unknown estimator", raw(message({ estimator: "model" }))],
    ["phones not a list", raw(message({ phones: {} }))],
    ["an unknown status", raw(message({ phones: [phone({ status: "busy" })] }))],
    ["a non-numeric position", raw(message({ phones: [phone({ position_m: { x: "1", y: 0, z: 0 } })] }))],
    ["a missing age", raw(message({ phones: [phone({ last_seen_age_s: "1" })] }))],
    ["a session id of the wrong type", raw(message({ phones: [phone({ session_id: 3 })] }))],
    [
      "a drone without distance",
      raw(message({ phones: [phone({ detection: { drone: true, distance_m: null, uncertainty_rel: null, age_s: 0, fresh: true } })] })),
    ],
    [
      "a distance without drone",
      raw(message({ phones: [phone({ detection: { drone: false, distance_m: 3, uncertainty_rel: 0.1, age_s: 0, fresh: true } })] })),
    ],
    [
      "a detection without freshness",
      raw(message({ phones: [phone({ detection: { drone: false, distance_m: null, uncertainty_rel: null, age_s: 0 } })] })),
    ],
    ["a phone that is not an object", raw(message({ phones: ["noe"] }))],
    ["a null phone", raw(message({ phones: [null] }))],
    ["a phone given as a list", raw(message({ phones: [[]] }))],
    ["a top-level list", raw([message()])],
    ["a missing server time", raw(message({ server_time: undefined }))],
    ["a detection that is not an object", raw(message({ phones: [phone({ detection: "far" })] }))],
    ["a non-numeric detection age", raw(message({ phones: [phone({ detection: { drone: false, distance_m: null, uncertainty_rel: null, age_s: "0", fresh: true } })] }))],
    ["a drone without uncertainty", raw(message({ phones: [phone({ detection: { drone: true, distance_m: 3, uncertainty_rel: null, age_s: 0, fresh: true } })] }))],
    ["no drone but an uncertainty", raw(message({ phones: [phone({ detection: { drone: false, distance_m: null, uncertainty_rel: 0.1, age_s: 0, fresh: true } })] }))],
    ["a non-boolean drone flag", raw(message({ phones: [phone({ detection: { drone: "yes", distance_m: null, uncertainty_rel: null, age_s: 0, fresh: true } })] }))],
    ["a drone view that is not an object", raw(message({ drone: "here" }))],
    ["an unknown drone status", raw(message({ drone: droneView({ status: "lost" }) }))],
    ["a located drone without zone", raw(message({ drone: droneView({ zone: null }) }))],
    ["a zone without location", raw(message({ drone: droneView({ status: "insufficient" }) }))],
    ["a non-numeric detecting count", raw(message({ drone: droneView({ detecting: "3" }) }))],
    ["a drone view without age", raw(message({ drone: droneView({ age_s: null }) }))],
    ["a zone with a missing field", raw(message({ drone: droneView({ zone: { x_m: 1, y_m: 2 } }) }))],
    [
      "a zone with a non-boolean degraded flag",
      raw(message({ drone: droneView({ zone: { ...droneView().zone, degraded: "no" } }) })),
    ],
    ["a true position without x", raw(message({ drone: droneView({ truth: { y_m: 1, z_m: 1 } }) }))],
    ["a true position without y", raw(message({ drone: droneView({ truth: { x_m: 1, z_m: 1 } }) }))],
    ["a true position without z", raw(message({ drone: droneView({ truth: { x_m: 1, y_m: 1 } }) }))],
    ["an unknown drone status without zone", raw(message({ drone: droneView({ status: "lost", zone: null }) }))],
  ])("rejects %s", (_name, text) => {
    expect(parseState(text)).toBeUndefined();
  });
});
