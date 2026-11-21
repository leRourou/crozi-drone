/** Doublures de test pour le module de capture et la WebSocket (utilisées par Vitest uniquement). */
import type {
  CaptureCallbacks,
  CaptureError,
  CaptureResult,
  CaptureSettings,
  CaptureStart,
  ContractId,
  PcmCapture,
  StopReason,
} from "@edth/capture";
import type { SocketLike } from "./streamer";

export function settings(contract: ContractId = "edth.web-pcm.v1"): CaptureSettings {
  return {
    capture_contract: contract,
    recorder: "audio_worklet_pcm",
    echoCancellation: false,
    noiseSuppression: contract === "edth.web-pcm.v1" ? false : null,
    autoGainControl: contract === "edth.web-pcm.v1" ? false : null,
    sample_rate: 48000,
    channels: 1,
    channel_selection: "first",
    input_channels: 1,
    sample_format: "pcm_s16le",
    browser: "test-agent",
    microphone_label: "Fake mic",
    track_settings: { echoCancellation: false },
    requested_constraints: {},
    system_processing: "unverified",
  };
}

export class FakeCapture implements PcmCapture {
  private chunks: Int16Array[] = [];
  private resolveStart!: (value: CaptureStart) => void;
  private rejectStart!: (error: unknown) => void;
  readonly started: Promise<CaptureStart>;
  disposed = false;
  stopCalls = 0;

  constructor(private readonly callbacks: CaptureCallbacks) {
    this.started = new Promise((resolve, reject) => {
      this.resolveStart = resolve;
      this.rejectStart = reject;
    });
  }

  start(): Promise<CaptureStart> {
    return this.started;
  }

  grant(contract: ContractId = "edth.web-pcm.v1"): void {
    this.resolveStart({ capturedAt: "2026-11-21T10:00:00.000Z", captureSettings: settings(contract) });
  }

  deny(code: string): void {
    this.rejectWith(Object.assign(new Error(`denied: ${code}`), { name: "CaptureError", code }));
  }

  rejectWith(error: unknown): void {
    this.rejectStart(error);
  }

  chunk(samples: Int16Array): void {
    this.chunks.push(samples.slice());
    this.callbacks.onLevel?.(0.5);
    this.callbacks.onChunk?.({
      samples,
      frameCount: samples.length,
      totalFrames: this.chunks.reduce((n, c) => n + c.length, 0),
      sampleRate: 48000,
      channels: 1,
      sampleFormat: "pcm_s16le",
    });
  }

  /** Comme le module : un seul onStopped, les appels suivants renvoient le même résultat. */
  async stop(reason: StopReason = "manual"): Promise<CaptureResult | null> {
    this.stopCalls += 1;
    if (this.stopped) return this.stopped;
    this.stopped = this.result(reason);
    this.callbacks.onStopped?.(this.stopped, reason);
    return this.stopped;
  }

  private stopped: CaptureResult | null = null;

  fail(code: string): void {
    const error = Object.assign(new Error(`failed: ${code}`), { name: "CaptureError", code });
    this.callbacks.onError?.(error as CaptureError);
  }

  dispose(): void {
    this.disposed = true;
  }

  pcmBytes(): Uint8Array {
    const frames = this.chunks.reduce((n, c) => n + c.length, 0);
    const out = new Int16Array(frames);
    let offset = 0;
    for (const c of this.chunks) {
      out.set(c, offset);
      offset += c.length;
    }
    return new Uint8Array(out.buffer);
  }

  private result(reason: StopReason): CaptureResult {
    const pcm = this.pcmBytes();
    const wav = new Uint8Array(44 + pcm.length);
    wav.set(pcm, 44);
    return {
      audioBase64: "",
      wavBytes: wav,
      frameCount: pcm.length / 2,
      sampleRate: 48000,
      channels: 1,
      channelSelection: "first",
      sampleFormat: "pcm_s16le",
      durationSeconds: pcm.length / 2 / 48000,
      capturedAt: "2026-11-21T10:00:00.000Z",
      captureSettings: settings(),
      hitLimit: reason === "limit",
    };
  }
}

export class FakeSocket implements SocketLike {
  binaryType: BinaryType = "blob";
  bufferedAmount = 0;
  sent: (string | ArrayBufferLike | Blob | ArrayBufferView)[] = [];
  closed = false;
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;

  constructor(readonly url: string) {}

  private get self(): WebSocket {
    return this as unknown as WebSocket; // doublure : seuls les membres de SocketLike sont lus
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.call(this.self, { code: 1000 } as CloseEvent);
  }

  open(): void {
    this.onopen?.call(this.self, new Event("open"));
  }

  receive(message: object): void {
    this.onmessage?.call(this.self, { data: JSON.stringify(message) } as MessageEvent);
  }

  drop(code = 1006): void {
    this.closed = true;
    this.onclose?.call(this.self, { code } as CloseEvent);
  }

  texts(): Record<string, unknown>[] {
    return this.sent.filter((m): m is string => typeof m === "string").map((m) => JSON.parse(m));
  }

  binaries(): ArrayBuffer[] {
    return this.sent.filter((m): m is ArrayBuffer => m instanceof ArrayBuffer);
  }
}
