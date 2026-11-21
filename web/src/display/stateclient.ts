/** Abonnement à /ws/state : transmet chaque état valide, se reconnecte avec un délai croissant. */
import { reconnectDelayMs } from "../shared/net";
import { parseState, type StateMessage } from "./state";

export type StateSocket = Pick<WebSocket, "close" | "onmessage" | "onclose">;
export type Connection = "connecting" | "connected" | "reconnecting" | "invalid";

export interface StateClientDeps {
  url: string;
  openSocket: (url: string) => StateSocket;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (id: unknown) => void;
}

export interface StateClientEvents {
  state: (state: StateMessage) => void;
  connection: (connection: Connection, retryInMs?: number) => void;
}

export class StateClient {
  private socket: StateSocket | null = null;
  private timer: unknown = null;
  private failures = 0;
  private connected = false;

  constructor(
    private readonly deps: StateClientDeps,
    private readonly events: StateClientEvents,
  ) {}

  start(): void {
    this.open();
  }

  stop(): void {
    if (this.timer !== null) this.deps.clearTimer(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
  }

  /** Relance tout de suite une reconnexion en attente ; sans effet sinon. Le délai croissant continue. */
  retryNow(): void {
    if (this.timer === null) return;
    this.deps.clearTimer(this.timer);
    this.open();
  }

  private open(): void {
    this.timer = null;
    this.connected = false;
    const socket = this.deps.openSocket(this.deps.url);
    this.socket = socket;
    this.events.connection("connecting");
    // Une socket remplacée (stop puis start) ne doit plus rien déclencher.
    socket.onmessage = (event) => {
      if (socket === this.socket) this.receive(String(event.data));
    };
    socket.onclose = () => {
      if (socket === this.socket) this.retry();
    };
  }

  private receive(text: string): void {
    const state = parseState(text);
    if (state === undefined) {
      this.connected = false;
      this.events.connection("invalid");
      return;
    }
    this.failures = 0;
    if (!this.connected) this.events.connection("connected");
    this.connected = true;
    this.events.state(state);
  }

  private retry(): void {
    const delay = reconnectDelayMs(this.failures);
    this.failures += 1;
    this.events.connection("reconnecting", delay);
    this.timer = this.deps.setTimer(() => this.open(), delay);
  }
}
