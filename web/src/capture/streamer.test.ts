import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeCapture, FakeSocket, settings } from "./fakes";
import { Streamer, type StreamerEvents, type Status } from "./streamer";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const tick = async () => {
  await vi.advanceTimersByTimeAsync(0);
};

function setup({ littleEndian = true } = {}) {
  const captures: FakeCapture[] = [];
  const sockets: FakeSocket[] = [];
  const logs: { text: string; level: string }[] = [];
  const statuses: Status[] = [];
  const levels: number[] = [];
  let uuidCounter = 0;
  const clock = { now: 1000 };
  const events: StreamerEvents = {
    log: (text, level = "info") => logs.push({ text, level }),
    status: (s) => statuses.push(s),
    level: (p) => levels.push(p),
  };
  const streamer = new Streamer(
    {
      createCapture: (callbacks) => {
        const capture = new FakeCapture(callbacks);
        captures.push(capture);
        return capture;
      },
      openSocket: (url) => {
        const socket = new FakeSocket(url);
        sockets.push(socket);
        return socket;
      },
      url: "wss://phone.test/ws/audio",
      uuid: () => `00000000-0000-4000-8000-00000000000${uuidCounter++}`,
      now: () => clock.now,
      userAgent: "test-agent",
      littleEndian,
      sha256Hex: async (bytes) => sha(bytes),
    },
    events,
  );
  const logText = () => logs.map((l) => l.text).join("\n");
  return { streamer, captures, sockets, logs, statuses, levels, logText, clock };
}

async function connect(env: ReturnType<typeof setup>, index = 0, contract = "edth.web-pcm.v1") {
  env.captures[index].grant(contract as "edth.web-pcm.v1");
  env.sockets[index].open();
  await tick();
  env.sockets[index].receive({ type: "ready", session_id: "x", server_time: 1 });
}

function sha(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("Streamer", () => {
  it("starts the capture synchronously, inside the user gesture", () => {
    const env = setup();
    env.streamer.start();
    expect(env.captures).toHaveLength(1);
    expect(env.sockets[0].url).toBe("wss://phone.test/ws/audio");
    expect(env.sockets[0].binaryType).toBe("arraybuffer");
  });

  it("sends a hello with the contract chosen by the module, then packets after ready", async () => {
    const env = setup();
    env.streamer.start();
    env.captures[0].grant();
    env.sockets[0].open();
    await tick();
    const hello = env.sockets[0].texts()[0];
    expect(hello).toEqual({
      type: "hello",
      protocol: "crozidrone.audio-stream.v1",
      session_id: "00000000-0000-4000-8000-000000000000",
      capture_settings: settings(),
      captured_at: "2026-11-21T10:00:00.000Z",
      user_agent: "test-agent",
    });
    env.captures[0].chunk(new Int16Array(2400).fill(3));
    expect(env.sockets[0].binaries()).toHaveLength(0);
    env.sockets[0].receive({ type: "ready", session_id: "x", server_time: 1 });
    expect(env.sockets[0].binaries()).toHaveLength(1);
    env.captures[0].chunk(new Int16Array(2400).fill(4));
    expect(env.sockets[0].binaries()).toHaveLength(2);
    expect(env.statuses.at(-1)).toMatchObject({ state: "streaming", contract: "edth.web-pcm.v1" });
    expect(env.levels).toEqual([0.5, 0.5]);
  });

  it("manual stop flushes, sends end with the WAV data hash and closes on end_ack", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.captures[0].chunk(Int16Array.from({ length: 3000 }, (_, i) => i - 1500));
    env.streamer.stop();
    await tick();
    const end = env.sockets[0].texts().at(-1);
    expect(end).toEqual({
      type: "end",
      reason: "manual",
      frames: 3000,
      pcm_sha256: sha(env.captures[0].pcmBytes()),
    });
    expect(env.sockets[0].binaries()).toHaveLength(2);
    env.sockets[0].receive({ type: "end_ack", frames_received: 3000, pcm_sha256: "ab", match: true });
    expect(env.sockets[0].closed).toBe(true);
    expect(env.logText()).toContain("end_ack frames=3000 match=✅");
    expect(env.statuses.at(-1)).toMatchObject({ state: "idle" });
    expect(env.captures).toHaveLength(1);
  });

  it("restarts a new capture and session automatically after the module limit", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.captures[0].chunk(new Int16Array(128));
    await env.captures[0].stop("limit");
    await tick();
    expect(env.sockets[0].texts().at(-1)).toMatchObject({ type: "end", reason: "limit" });
    env.sockets[0].receive({ type: "end_ack", frames_received: 128, pcm_sha256: "x", match: true });
    expect(env.captures).toHaveLength(2);
    expect(env.logText()).toMatch(/limit.*nouvelle session/);
    env.clock.now = 1250;
    await connect(env, 1);
    expect(env.sockets[1].texts()[0]).toMatchObject({
      session_id: "00000000-0000-4000-8000-000000000001",
    });
    const granted = env.logs.filter((l) => l.text.startsWith("micro ok")).map((l) => l.text);
    expect(granted[0]).not.toContain("gap_ms");
    expect(granted[1]).toMatch(/ gap_ms=250$/);
  });

  it("a module error ends the session explicitly, without hash and without restart", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.captures[0].chunk(new Int16Array(100));
    env.captures[0].fail("audio-interrupted");
    expect(env.sockets[0].texts().at(-1)).toEqual({ type: "end", reason: "error", frames: 100 });
    expect(env.sockets[0].closed).toBe(true);
    expect(env.logs).toContainEqual(expect.objectContaining({ level: "error" }));
    expect(env.logText()).toContain("audio-interrupted");
    expect(env.statuses.at(-1)).toMatchObject({ state: "error" });
    expect(env.captures).toHaveLength(1);
  });

  it("a refused microphone is logged with its code and closes the socket", async () => {
    const env = setup();
    env.streamer.start();
    env.captures[0].deny("permission-denied");
    await tick();
    expect(env.logText()).toContain("permission-denied");
    expect(env.sockets[0].closed).toBe(true);
    expect(env.statuses.at(-1)).toMatchObject({ state: "error" });
  });

  it("an unexpected socket close stops the capture without restarting", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.sockets[0].drop(1006);
    expect(env.captures[0].disposed).toBe(true);
    expect(env.logText()).toContain("ws_closed code=1006");
    expect(env.statuses.at(-1)).toMatchObject({ state: "error" });
    expect(env.captures).toHaveLength(1);
  });

  it("a socket that never opens disposes the capture", async () => {
    const env = setup();
    env.streamer.start();
    env.captures[0].grant();
    env.sockets[0].drop(1006);
    await tick();
    expect(env.captures[0].disposed).toBe(true);
    expect(env.statuses.at(-1)).toMatchObject({ state: "error" });
  });

  it("a server error is logged", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.sockets[0].receive({ type: "error", code: "discontinuity", message: "expected=1 got=2" });
    env.sockets[0].drop(1008);
    expect(env.logText()).toContain("server_error code=discontinuity");
  });

  it("shows the WebKit warning when the module picks the WebKit profile", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env, 0, "edth.web-pcm.webkit.v1");
    expect(env.statuses.at(-1)).toMatchObject({ contract: "edth.web-pcm.webkit.v1", webkit: true });
    expect(env.logs).toContainEqual(expect.objectContaining({ level: "warn" }));
  });

  it("pings every 2 s, logs tx counters and the round-trip time", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    await vi.advanceTimersByTimeAsync(2000);
    expect(env.sockets[0].texts().at(-1)).toEqual({ type: "ping", t: 1000 });
    expect(env.logText()).toMatch(/tx pkts=0 frames=0 buffered=0B/);
    env.sockets[0].receive({ type: "pong", t: 958 });
    expect(env.logText()).toContain("rtt=42ms");
  });

  it("logs server stats readably", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.sockets[0].receive({
      type: "stats", packets_per_s: 20, audio_s: 3.2, rt_ratio: 1.004, kbps: 768,
      peak_dbfs: -6.02, rms_dbfs: null, max_gap_ms: 61.2, gaps: 0,
    });
    expect(env.logText()).toContain(
      "stats pps=20.0 audio=3.2s rt=1.00 kbps=768 peak=-6.0dBFS rms=-∞dBFS gap_max=61ms gaps=0",
    );
  });

  it("refuses to start on a big-endian platform", () => {
    const env = setup({ littleEndian: false });
    env.streamer.start();
    expect(env.captures).toHaveLength(0);
    expect(env.logs[0]).toMatchObject({ level: "error" });
  });

  it("ignores a second start while a session is active", async () => {
    const env = setup();
    env.streamer.start();
    env.streamer.start();
    expect(env.captures).toHaveLength(1);
    await flush;
  });
});

describe("subtleSha256Hex", () => {
  it("matches the reference SHA-256 of 'abc'", async () => {
    const { subtleSha256Hex } = await import("./streamer");
    expect(await subtleSha256Hex(new TextEncoder().encode("abc"))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("hashes only the given view, not its whole buffer", async () => {
    const { subtleSha256Hex } = await import("./streamer");
    const wav = new Uint8Array(47);
    wav.set(new TextEncoder().encode("abc"), 44);
    expect(await subtleSha256Hex(wav.subarray(44))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});

describe("Streamer edge cases", () => {
  it("logs a mismatching end_ack as a warning", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.streamer.stop();
    await tick();
    env.sockets[0].receive({ type: "end_ack", frames_received: 0, pcm_sha256: "x", match: false });
    expect(env.logs).toContainEqual({ text: "end_ack frames=0 match=❌", level: "warn" });
  });

  it("logs an error without code as unknown", async () => {
    const env = setup();
    env.streamer.start();
    env.captures[0].rejectWith(new Error("boom"));
    await tick();
    expect(env.logText()).toContain("code=unknown boom");
  });
});

describe("Streamer lifecycle", () => {
  it("logs the short session id when the microphone opens and when ready", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    expect(env.logText()).toContain("micro ok session=00000000 contract=edth.web-pcm.v1");
    expect(env.logs).toContainEqual({ text: "ready session=00000000", level: "info" });
  });

  it("stops pinging once the session is finished", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.streamer.stop();
    await tick();
    env.sockets[0].receive({ type: "end_ack", frames_received: 0, pcm_sha256: "x", match: true });
    const sentBefore = env.sockets[0].sent.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(env.sockets[0].sent.length).toBe(sentBefore);
  });

  it("can start again after a manual stop", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    env.streamer.stop();
    await tick();
    env.sockets[0].receive({ type: "end_ack", frames_received: 0, pcm_sha256: "x", match: true });
    env.streamer.start();
    expect(env.captures).toHaveLength(2);
  });

  it("does not restart when the user stops while a limit stop is in flight", async () => {
    const env = setup();
    env.streamer.start();
    await connect(env);
    await env.captures[0].stop("limit");
    env.streamer.stop();
    await tick();
    env.sockets[0].receive({ type: "end_ack", frames_received: 0, pcm_sha256: "x", match: true });
    expect(env.captures).toHaveLength(1);
    expect(env.statuses.at(-1)).toMatchObject({ state: "idle" });
  });

  it("stop before any start is harmless", () => {
    const env = setup();
    expect(() => env.streamer.stop()).not.toThrow();
  });
});
