/**
 * Types du module partagé vendor/edth/audio_capture.js (non converti, jamais modifié).
 * Vérifiés à la main contre la version SHA-256 77d337fd…6aeb.
 */
declare module "@edth/capture" {
  export type ContractId = "edth.web-pcm.v1" | "edth.web-pcm.webkit.v1";

  export interface CaptureContract {
    readonly id: ContractId;
    readonly version: number;
    readonly recorder: "audio_worklet_pcm";
    readonly sample_rate: 48000;
    readonly channels: 1;
    readonly channel_selection: "first";
    readonly sample_format: "pcm_s16le";
    readonly max_audio_bytes: number;
    readonly max_frames: number;
    readonly processing_verification?: "webkit_echo_cancellation_only";
  }

  export interface CaptureSettings {
    capture_contract: ContractId;
    recorder: "audio_worklet_pcm";
    echoCancellation: boolean;
    noiseSuppression: boolean | null;
    autoGainControl: boolean | null;
    processing_verification?: "webkit_echo_cancellation_only";
    supported_constraints?: Record<string, boolean>;
    sample_rate: 48000;
    channels: 1;
    channel_selection: "first";
    input_channels: number | null;
    sample_format: "pcm_s16le";
    browser: string;
    microphone_label: string;
    track_settings: Record<string, unknown>;
    requested_constraints: Record<string, unknown>;
    system_processing: "unverified";
  }

  export interface CaptureStart {
    capturedAt: string;
    captureSettings: CaptureSettings;
  }

  export interface PcmChunk {
    samples: Int16Array;
    frameCount: number;
    totalFrames: number;
    sampleRate: 48000;
    channels: 1;
    sampleFormat: "pcm_s16le";
  }

  export interface CaptureResult {
    audioBase64: string;
    wavBytes: Uint8Array;
    frameCount: number;
    sampleRate: 48000;
    channels: 1;
    channelSelection: "first";
    sampleFormat: "pcm_s16le";
    durationSeconds: number;
    capturedAt: string;
    captureSettings: CaptureSettings;
    hitLimit: boolean;
  }

  export type StopReason = "manual" | "limit";

  export interface CaptureError extends Error {
    name: "CaptureError";
    code: string;
  }

  export interface CaptureCallbacks {
    onChunk?: (chunk: PcmChunk) => void;
    onLevel?: (peak: number) => void;
    onError?: (error: CaptureError) => void;
    onStopped?: (result: CaptureResult, reason: StopReason) => void;
  }

  export interface PcmCapture {
    start(): Promise<CaptureStart>;
    stop(reason?: StopReason): Promise<CaptureResult | null>;
    dispose(): void;
  }

  export const CAPTURE_CONTRACT: CaptureContract;
  export const WEBKIT_CAPTURE_CONTRACT: CaptureContract;
  export const MAX_FRAMES: number;
  export const WAV_HEADER_BYTES: number;
  export function getCaptureSupport(options?: {
    userAgent?: string;
    supportedConstraints?: Record<string, boolean>;
  }): { contract: CaptureContract; supportedConstraints: Record<string, boolean> };
  export function createPcmCapture(callbacks?: CaptureCallbacks): PcmCapture;
}
