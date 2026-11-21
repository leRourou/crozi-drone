import { beforeEach, describe, expect, it } from "vitest";
import { type Connection, StateClient, type StateSocket } from "./stateclient";
import type { StateMessage } from "./state";
import { message } from "./fakes";

class FakeSocket implements StateSocket {
  onmessage: StateSocket["onmessage"] = null;
  onclose: StateSocket["onclose"] = null;
  closed = 0;
  constructor(readonly url: string) {}
  close(): void {
    this.closed += 1;
  }
  receive(data: unknown): void {
    this.onmessage?.call(this as never, { data } as MessageEvent);
  }
  drop(): void {
    this.onclose?.call(this as never, {} as CloseEvent);
  }
}

let sockets: FakeSocket[];
let timers: { fn: () => void; ms: number; cleared: boolean }[];
let states: StateMessage[];
let connections: [Connection, number?][];
let client: StateClient;

beforeEach(() => {
  sockets = [];
  timers = [];
  states = [];
  connections = [];
  client = new StateClient(
    {
      url: "wss://pc.test/ws/state",
      openSocket: (url) => {
        const socket = new FakeSocket(url);
        sockets.push(socket);
        return socket;
      },
      setTimer: (fn, ms) => timers.push({ fn, ms, cleared: false }) - 1,
      clearTimer: (id) => {
        timers[id as number].cleared = true;
      },
    },
    { state: (s) => states.push(s), connection: (c, retryInMs) => connections.push([c, retryInMs]) },
  );
});

const valid = () => JSON.stringify(message());

describe("StateClient", () => {
  it("connects to the state endpoint and announces it", () => {
    client.start();
    expect(sockets.map((s) => s.url)).toEqual(["wss://pc.test/ws/state"]);
    expect(connections).toEqual([["connecting", undefined]]);
  });

  it("forwards every valid state and reports the connection once", () => {
    client.start();
    sockets[0].receive(valid());
    sockets[0].receive(valid());
    expect(states).toHaveLength(2);
    expect(states[0].estimator).toBe("scripted");
    expect(connections.map(([c]) => c)).toEqual(["connecting", "connected"]);
  });

  it("does not forward an invalid message and reports it", () => {
    client.start();
    sockets[0].receive("{}");
    expect(states).toEqual([]);
    expect(connections.at(-1)).toEqual(["invalid", undefined]);
  });

  it("reconnects after a drop with a growing delay", () => {
    client.start();
    sockets[0].drop();
    expect(connections.at(-1)).toEqual(["reconnecting", 1000]);
    timers[0].fn();
    expect(sockets).toHaveLength(2);
    sockets[1].drop();
    expect(timers.map((t) => t.ms)).toEqual([1000, 2000]);
  });

  it("starts again from 1 s once a state was received", () => {
    client.start();
    sockets[0].drop();
    timers[0].fn();
    sockets[1].receive(valid());
    sockets[1].drop();
    expect(timers.map((t) => t.ms)).toEqual([1000, 1000]);
  });

  it("stop closes the socket, cancels a pending retry and never reconnects", () => {
    client.start();
    sockets[0].drop();
    client.stop();
    expect(timers[0].cleared).toBe(true);
    expect(sockets[0].closed).toBe(1);
    sockets[0].drop();
    expect(timers).toHaveLength(1);
  });

  it("ignores the close of a socket it already replaced (stop then start, as React StrictMode does)", () => {
    client.start();
    client.stop();
    client.start();
    sockets[0].drop();
    expect(timers).toEqual([]);
    expect(sockets).toHaveLength(2);
  });

  it("reports the connection as soon as the first state arrives", () => {
    client.start();
    sockets[0].receive(valid());
    expect(connections.at(-1)).toEqual(["connected", undefined]);
  });

  it("reports connected again when a valid state follows an invalid one", () => {
    client.start();
    sockets[0].receive(valid());
    sockets[0].receive("{}");
    sockets[0].receive(valid());
    expect(connections.map(([c]) => c)).toEqual(["connecting", "connected", "invalid", "connected"]);
  });

  it("retryNow cancels the pending wait and reconnects at once", () => {
    client.start();
    sockets[0].drop();
    client.retryNow();
    expect(timers[0].cleared).toBe(true);
    expect(sockets).toHaveLength(2);
    expect(connections.at(-1)).toEqual(["connecting", undefined]);
  });

  it("retryNow keeps the growing delay if the server is still down", () => {
    client.start();
    sockets[0].drop();
    client.retryNow();
    sockets[1].drop();
    expect(timers.map((t) => t.ms)).toEqual([1000, 2000]);
  });

  it("retryNow does nothing while connected or after stop", () => {
    client.start();
    sockets[0].receive(valid());
    client.retryNow();
    expect(sockets).toHaveLength(1);
    sockets[0].drop();
    client.stop();
    client.retryNow();
    expect(sockets).toHaveLength(1);
  });

  it("stop is harmless before start and when called twice", () => {
    client.stop();
    client.start();
    client.stop();
    client.stop();
    expect(sockets[0].closed).toBe(1);
  });
});
