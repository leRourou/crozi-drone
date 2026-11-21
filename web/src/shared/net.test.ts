import { describe, expect, it } from "vitest";
import { reconnectDelayMs, socketUrl } from "./net";

describe("reconnectDelayMs", () => {
  it("doubles from 1 s after each failure and caps at 30 s", () => {
    expect([0, 1, 2, 3, 4, 5, 6, 20].map(reconnectDelayMs)).toEqual([
      1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000,
    ]);
  });
});

describe("socketUrl", () => {
  it("uses wss on an https page, same host", () => {
    expect(socketUrl("/ws/state", { protocol: "https:", host: "x.ts.net" })).toBe("wss://x.ts.net/ws/state");
  });

  it("uses ws on an http page (localhost)", () => {
    expect(socketUrl("/ws/audio", { protocol: "http:", host: "127.0.0.1:5173" })).toBe(
      "ws://127.0.0.1:5173/ws/audio",
    );
  });
});
