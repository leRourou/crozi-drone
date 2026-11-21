/**
 * Chaîne temps réel côté téléphone : module partagé → paquets → WebSocket crozidrone.audio-stream.v1.
 * 1 capture = 1 session (UUID) = 1 WebSocket. Le module de capture n'est jamais contourné.
 */
import type {
  CaptureCallbacks,
  CaptureError,
  CaptureResult,
  CaptureStart,
  ContractId,
  PcmCapture,
  StopReason,
} from "@edth/capture";
import { WEBKIT_CAPTURE_CONTRACT } from "@edth/capture";
import { Packetizer } from "./packetizer";

export const PROTOCOL = "crozidrone.audio-stream.v1";
const WAV_HEADER_BYTES = 44;
const PING_PERIOD_MS = 2000;

export type LogLevel = "info" | "warn" | "error";
export type State = "idle" | "starting" | "streaming" | "error";
export interface Status {
  state: State;
  contract?: ContractId;
  webkit?: boolean;
  sessionId?: string;
}

/** Sous-ensemble de WebSocket utilisé ici (remplaçable par une doublure en test). */
export type SocketLike = Pick<
  WebSocket,
  "binaryType" | "bufferedAmount" | "send" | "close" | "onopen" | "onmessage" | "onclose" | "onerror"
>;

export interface StreamerDeps {
  createCapture: (callbacks: CaptureCallbacks) => PcmCapture;
  openSocket: (url: string) => SocketLike;
  url: string;
  uuid: () => string;
  now: () => number;
  userAgent: string;
  littleEndian: boolean;
  sha256Hex: (bytes: Uint8Array) => Promise<string>;
}

export interface StreamerEvents {
  log: (text: string, level?: LogLevel) => void;
  status: (status: Status) => void;
  level: (peak: number) => void;
}

type Outcome = StopReason | "error" | "disconnect";

interface ServerStats {
  packets_per_s: number;
  audio_s: number;
  rt_ratio: number;
  kbps: number;
  peak_dbfs: number | null;
  rms_dbfs: number | null;
  max_gap_ms: number;
  gaps: number;
}

export async function subtleSha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as Uint8Array<ArrayBuffer>);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

const db = (value: number | null) => (value === null ? "-∞" : value.toFixed(1));

export function formatStats(s: ServerStats): string {
  return (
    `stats pps=${s.packets_per_s.toFixed(1)} audio=${s.audio_s.toFixed(1)}s ` +
    `rt=${s.rt_ratio.toFixed(2)} kbps=${s.kbps.toFixed(0)} peak=${db(s.peak_dbfs)}dBFS ` +
    `rms=${db(s.rms_dbfs)}dBFS gap_max=${s.max_gap_ms.toFixed(0)}ms gaps=${s.gaps}`
  );
}

function captureErrorText(error: unknown): string {
  const e = error as Partial<CaptureError>;
  return `code=${e.code || "unknown"} ${e.message || String(error)}`;
}

/** Une capture et sa WebSocket, de l'ouverture à end_ack. */
class Session {
  readonly id: string;
  private readonly capture: PcmCapture;
  private readonly socket: SocketLike;
  private readonly packetizer: Packetizer;
  private readonly queue: ArrayBuffer[] = [];
  private ready = false;
  private done = false;
  private pinger: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly deps: StreamerDeps,
    private readonly events: StreamerEvents,
    private readonly onFinished: (outcome: Outcome) => void,
    private readonly restartedAt: number | null,
  ) {
    this.id = deps.uuid();
    this.packetizer = new Packetizer((packet) => this.sendPacket(packet));
    this.capture = deps.createCapture({
      onChunk: (chunk) => this.packetizer.push(chunk.samples),
      onLevel: (peak) => events.level(peak),
      onError: (error) => this.failCapture(error),
      onStopped: (result, reason) => void this.end(result, reason),
    });
    const started = this.capture.start(); // dans le geste utilisateur
    this.socket = deps.openSocket(deps.url);
    this.socket.binaryType = "arraybuffer";
    void this.connect(started, this.opened());
  }

  stop(): void {
    void this.capture.stop("manual");
  }

  private opened(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket.onopen = () => resolve();
      this.socket.onerror = () => undefined; // le détail arrive par onclose
      this.socket.onclose = (event) => {
        reject(new Error(`ws_closed code=${event.code}`));
        this.closed(event.code);
      };
      this.socket.onmessage = (event) => this.receive(String(event.data));
    });
  }

  private async connect(started: Promise<CaptureStart>, opened: Promise<void>): Promise<void> {
    opened.catch(() => undefined);
    let start: CaptureStart;
    try {
      start = await started;
    } catch (error) {
      this.finish("error", `micro refusé ${captureErrorText(error)}`);
      return;
    }
    if (this.done) return; // socket fermée pendant l'ouverture du micro
    this.logGranted(start);
    try {
      await opened;
    } catch {
      return; // closed() a déjà terminé la session
    }
    this.socket.send(
      JSON.stringify({
        type: "hello",
        protocol: PROTOCOL,
        session_id: this.id,
        capture_settings: start.captureSettings,
        captured_at: start.capturedAt,
        user_agent: this.deps.userAgent,
      }),
    );
  }

  private logGranted({ captureSettings: s }: CaptureStart): void {
    const gap = this.restartedAt === null ? "" : ` gap_ms=${(this.deps.now() - this.restartedAt).toFixed(0)}`;
    this.events.log(
      `micro ok session=${this.id.slice(0, 8)} contract=${s.capture_contract} mic="${s.microphone_label}" ` +
        `ec=${s.echoCancellation} ns=${s.noiseSuppression} agc=${s.autoGainControl}${gap}`,
    );
    const webkit = s.capture_contract === WEBKIT_CAPTURE_CONTRACT.id;
    if (webkit) {
      this.events.log("profil WebKit : seul l'anti-écho est vérifié (NS/AGC inconnus)", "warn");
    }
    this.events.status({ state: "starting", contract: s.capture_contract, webkit, sessionId: this.id });
    this.contract = { contract: s.capture_contract, webkit, sessionId: this.id };
  }

  private contract: Omit<Status, "state"> = {};

  private sendPacket(packet: ArrayBuffer): void {
    if (this.ready) this.socket.send(packet);
    else this.queue.push(packet);
  }

  private receive(text: string): void {
    const msg = JSON.parse(text) as { type: string } & Record<string, unknown>;
    switch (msg.type) {
      case "ready":
        return this.onReady();
      case "pong":
        return this.events.log(`rtt=${(this.deps.now() - Number(msg.t)).toFixed(0)}ms`);
      case "stats":
        return this.events.log(formatStats(msg as unknown as ServerStats));
      case "end_ack":
        return this.onEndAck(msg);
      case "error":
        return this.events.log(`server_error code=${msg.code} ${msg.message}`, "error");
    }
  }

  private onReady(): void {
    this.ready = true;
    this.events.log(`ready session=${this.id.slice(0, 8)}`);
    this.queue.splice(0).forEach((packet) => this.socket.send(packet));
    this.events.status({ state: "streaming", ...this.contract });
    this.pinger = setInterval(() => this.ping(), PING_PERIOD_MS);
  }

  private ping(): void {
    const p = this.packetizer;
    this.events.log(`tx pkts=${p.packetsSent} frames=${p.framesSent} buffered=${this.socket.bufferedAmount}B`);
    this.socket.send(JSON.stringify({ type: "ping", t: this.deps.now() }));
  }

  private pendingOutcome: Outcome = "manual";

  private async end(result: CaptureResult, reason: StopReason): Promise<void> {
    this.packetizer.flush();
    const digest = await this.deps.sha256Hex(result.wavBytes.subarray(WAV_HEADER_BYTES));
    this.pendingOutcome = reason;
    this.socket.send(JSON.stringify({ type: "end", reason, frames: result.frameCount, pcm_sha256: digest }));
  }

  private onEndAck(msg: Record<string, unknown>): void {
    const ok = msg.match === true;
    this.events.log(`end_ack frames=${msg.frames_received} match=${ok ? "✅" : "❌"}`, ok ? "info" : "warn");
    this.finish(this.pendingOutcome);
  }

  private failCapture(error: CaptureError): void {
    this.packetizer.flush();
    this.socket.send(JSON.stringify({ type: "end", reason: "error", frames: this.packetizer.framesSent }));
    this.finish("error", `erreur capture ${captureErrorText(error)} — session terminée`);
  }

  private closed(code: number): void {
    if (this.done) return;
    this.capture.dispose();
    this.finish("disconnect", `ws_closed code=${code} — capture arrêtée`);
  }

  private finish(outcome: Outcome, errorText?: string): void {
    if (this.done) return;
    this.done = true;
    if (this.pinger !== null) clearInterval(this.pinger);
    if (errorText) this.events.log(errorText, "error");
    this.socket.close();
    this.onFinished(outcome);
  }
}

/** Démarre/arrête les sessions et relance automatiquement après la limite du module (~175 s). */
export class Streamer {
  private session: Session | null = null;
  private active = false;

  constructor(
    private readonly deps: StreamerDeps,
    private readonly events: StreamerEvents,
  ) {}

  /** À appeler directement dans le gestionnaire du clic (geste utilisateur). */
  start(): void {
    if (this.active) return;
    if (!this.deps.littleEndian) {
      this.events.log("plateforme big-endian : envoi Int16 LE impossible, démarrage refusé", "error");
      this.events.status({ state: "error" });
      return;
    }
    this.active = true;
    this.events.status({ state: "starting" });
    this.open(null);
  }

  stop(): void {
    this.active = false;
    this.session?.stop();
  }

  private open(restartedAt: number | null): void {
    this.session = new Session(this.deps, this.events, (outcome) => this.finished(outcome), restartedAt);
  }

  private finished(outcome: Outcome): void {
    if (outcome === "limit" && this.active) {
      this.events.log("limite du module (~175 s) atteinte : nouvelle session, trou assumé", "warn");
      this.open(this.deps.now());
      return;
    }
    this.active = false;
    this.session = null;
    const clean = outcome === "manual" || outcome === "limit"; // fin propre voulue par l'utilisateur
    this.events.status({ state: clean ? "idle" : "error" });
  }
}
