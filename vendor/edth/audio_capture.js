/**
 * EDTH reusable Web Audio PCM capture core (no Streamlit dependency).
 *
 * Mono-output 48 kHz PCM16 capture with no compressor, gain, analyser,
 * app-side resampling, normalization or codec. Source tracks may have more
 * than one channel; only channel 0 is recorded, never mixed. The browser's
 * 48 kHz context may still convert a 44.1 kHz source, but the app adds no
 * resampling stage. The Streamlit adapter (recorder.js) and a future web
 * product share this worklet, S16 quantization and WAV code. Strict v1 checks
 * all DSP flags; the distinct WebKit profile checks AEC and keeps unexposed
 * NS/AGC settings unknown. Neither profile invents disabled settings.
 * system_processing stays "unverified": OS/hardware DSP cannot be certified.
 */

const SAMPLE_RATE = 48_000;
const CHANNELS = 1;
const SAMPLE_FORMAT = "pcm_s16le";
const WORKLET_NAME = "edth-pcm-tap";
const STOP_ACK_TIMEOUT_MS = 2000;
export const MAX_AUDIO_BYTES = 16 * 1024 * 1024;
export const WAV_HEADER_BYTES = 44;
export const MAX_FRAMES = Math.floor((MAX_AUDIO_BYTES - WAV_HEADER_BYTES) / 2);

export const SUPPORTED_PROCESSING_FLAGS = Object.freeze([
  "echoCancellation",
  "noiseSuppression",
  "autoGainControl",
]);

export const REQUESTED_CONSTRAINTS = Object.freeze({
  echoCancellation: Object.freeze({ exact: false }),
  noiseSuppression: Object.freeze({ exact: false }),
  autoGainControl: Object.freeze({ exact: false }),
  channelCount: Object.freeze({ ideal: 1 }),
  sampleRate: Object.freeze({ ideal: SAMPLE_RATE }),
});

export const CAPTURE_CONTRACT = Object.freeze({
  id: "edth.web-pcm.v1",
  version: 1,
  recorder: "audio_worklet_pcm",
  sample_rate: SAMPLE_RATE,
  channels: CHANNELS,
  channel_selection: "first",
  sample_format: SAMPLE_FORMAT,
  max_audio_bytes: MAX_AUDIO_BYTES,
  max_frames: MAX_FRAMES,
  format: Object.freeze({
    sample_rate: SAMPLE_RATE,
    channels: CHANNELS,
    channel_selection: "first",
    sample_format: SAMPLE_FORMAT,
  }),
  constraints: REQUESTED_CONSTRAINTS,
});

// Separate provenance: WebKit does not expose independent NS/AGC switches.
// echoCancellation:false selects its non-VoiceProcessingIO path, but is not
// a runtime confirmation for those two missing settings (nor for OS DSP).
export const WEBKIT_REQUESTED_CONSTRAINTS = Object.freeze({
  ...REQUESTED_CONSTRAINTS,
  // Older WebKit rejects {exact:false} even when EC can be disabled. Request
  // false once, then require the same strict getSettings() false postcondition.
  echoCancellation: false,
});
export const WEBKIT_CAPTURE_CONTRACT = Object.freeze({
  ...CAPTURE_CONTRACT,
  id: "edth.web-pcm.webkit.v1",
  constraints: WEBKIT_REQUESTED_CONSTRAINTS,
  processing_verification: "webkit_echo_cancellation_only",
});

export function isAppleWebKit(userAgent) {
  return typeof userAgent === "string"
    && /AppleWebKit\//.test(userAgent)
    && /(iPhone|iPad|iPod|Macintosh.*Mac OS X)/.test(userAgent)
    && !/(Android|Chrome\/|Chromium\/|Edg\/|OPR\/)/.test(userAgent);
}

export function getCaptureSupport({
  userAgent = globalThis.navigator?.userAgent || "",
  supportedConstraints = globalThis.navigator?.mediaDevices?.getSupportedConstraints?.() || {},
} = {}) {
  const supported = { ...supportedConstraints };
  if (SUPPORTED_PROCESSING_FLAGS.every((flag) => supported[flag] === true)) {
    return { contract: CAPTURE_CONTRACT, supportedConstraints: supported };
  }
  if (isAppleWebKit(userAgent) && supported.echoCancellation === true
      && SUPPORTED_PROCESSING_FLAGS.every((flag) =>
        supported[flag] === undefined || typeof supported[flag] === "boolean")) {
    return { contract: WEBKIT_CAPTURE_CONTRACT, supportedConstraints: supported };
  }
  throw captureError("unsupported-constraints");
}

const WORKLET_SOURCE = `
class EdthPcmTapProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.active = true;
    this.port.onmessage = (event) => {
      if (event.data && event.data.type === "stop") {
        this.active = false;
        this.port.postMessage({ type: "stopped" });
      }
    };
  }

  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0);
    if (!this.active) return true;
    const input = inputs[0];
    if (!input || !input[0] || !input[0].length) return true;
    const copy = input[0].slice();
    this.port.postMessage(copy.buffer, [copy.buffer]);
    return true;
  }
}
registerProcessor("${WORKLET_NAME}", EdthPcmTapProcessor);
`;

const MESSAGES = {
  "insecure-context": "Audio capture requires HTTPS or localhost.",
  unsupported: "This browser lacks a required audio capture API.",
  "unsupported-constraints": "The browser does not report all strict DSP constraints.",
  "permission-denied": "Microphone permission was denied.",
  "no-microphone": "No microphone is available.",
  "microphone-busy": "The microphone is already in use.",
  "microphone-failed": "The microphone could not be opened.",
  "constraints-unsatisfied": "The microphone rejected the strict DSP or channel constraints.",
  "processing-enabled": "The browser did not confirm all DSP flags are false.",
  "channels-unavailable": "The browser did not report a valid input channel count.",
  "track-unavailable": "Exactly one live audio track is required.",
  "audio-interrupted": "The audio track or context is no longer running.",
  "context-unsupported": "A running 48 kHz audio context is required.",
  "sample-rate-mismatch": "The audio context did not open at 48 kHz.",
  "worklet-failed": "The PCM audio worklet failed to load.",
  cancelled: "Capture start was cancelled.",
  busy: "This capture is already active.",
  disposed: "This capture was disposed.",
  "no-audio": "No audio frames were captured.",
  "invalid-pcm": "PCM chunks must be Int16Array instances.",
  "audio-limit": "The WAV exceeds the 16 MiB capture limit.",
  "stop-timeout": "The audio worklet did not acknowledge the stop.",
};

function captureError(code, cause) {
  const error = new Error(MESSAGES[code] || code);
  error.name = "CaptureError";
  error.code = code;
  if (cause !== undefined) error.cause = cause;
  return error;
}

const MEDIA_CODES = {
  NotAllowedError: "permission-denied",
  SecurityError: "permission-denied",
  NotFoundError: "no-microphone",
  DevicesNotFoundError: "no-microphone",
  NotReadableError: "microphone-busy",
  TrackStartError: "microphone-busy",
  OverconstrainedError: "constraints-unsatisfied",
  ConstraintNotSatisfiedError: "constraints-unsatisfied",
  AbortError: "audio-interrupted",
};

function microphoneError(cause) {
  return captureError(MEDIA_CODES[cause?.name] || "microphone-failed", cause);
}

function requireApi() {
  if (globalThis.isSecureContext === false) throw captureError("insecure-context");
  if (!globalThis.navigator?.mediaDevices?.getUserMedia) throw captureError("unsupported");
  if (!globalThis.AudioContext && !globalThis.webkitAudioContext) {
    throw captureError("unsupported");
  }
  if (!globalThis.AudioWorkletNode) throw captureError("unsupported");
}

export function readTrackSettings(track) {
  const reported = track && typeof track.getSettings === "function" ? track.getSettings() : {};
  const settings = {};
  for (const [key, value] of Object.entries(reported || {})) {
    if (value !== undefined) settings[key] = value;
  }
  return settings;
}

export function verifyTrack(track, { contract = CAPTURE_CONTRACT, supportedConstraints = {} } = {}) {
  if (!track || track.kind !== "audio") throw captureError("track-unavailable");
  const settings = readTrackSettings(track);
  const webkit = contract.id === WEBKIT_CAPTURE_CONTRACT.id;
  for (const flag of SUPPORTED_PROCESSING_FLAGS) {
    const unexposed = webkit && flag !== "echoCancellation"
      && supportedConstraints[flag] !== true && !Object.hasOwn(settings, flag);
    if (!unexposed && settings[flag] !== false) throw captureError("processing-enabled");
  }
  const unexposedChannels = webkit && !Object.hasOwn(settings, "channelCount");
  if (!unexposedChannels && (!Number.isInteger(settings.channelCount) || settings.channelCount < 1)) {
    throw captureError("channels-unavailable");
  }
  if (track.readyState !== "live" || track.enabled !== true || track.muted !== false) {
    throw captureError("audio-interrupted");
  }
  return settings;
}

/**
 * `track_settings` is the actual getSettings() report. A source sample rate
 * other than 48 kHz is expected (Firefox does not expose it); Web Audio
 * converts it to the explicit context rate, so only track_settings reflects it.
 * `input_channels` may be greater than one; the recording is always channel 0
 * only (channel_selection "first"), never a mix or average.
 */
export function buildCaptureSettings({ track, userAgent, contract = CAPTURE_CONTRACT, supportedConstraints = {} }) {
  const trackSettings = verifyTrack(track, { contract, supportedConstraints });
  const webkit = contract.id === WEBKIT_CAPTURE_CONTRACT.id;
  return {
    capture_contract: contract.id,
    recorder: contract.recorder,
    echoCancellation: trackSettings.echoCancellation,
    noiseSuppression: trackSettings.noiseSuppression ?? null,
    autoGainControl: trackSettings.autoGainControl ?? null,
    ...(webkit ? {
      processing_verification: WEBKIT_CAPTURE_CONTRACT.processing_verification,
      supported_constraints: { ...supportedConstraints },
    } : {}),
    sample_rate: SAMPLE_RATE,
    channels: CHANNELS,
    channel_selection: "first",
    input_channels: trackSettings.channelCount ?? null,
    sample_format: SAMPLE_FORMAT,
    browser: typeof userAgent === "string" ? userAgent : "",
    microphone_label: typeof track.label === "string" ? track.label : "",
    track_settings: trackSettings,
    requested_constraints: {
      echoCancellation: webkit ? false : { exact: false },
      noiseSuppression: { exact: false },
      autoGainControl: { exact: false },
      channelCount: { ideal: 1 },
      sampleRate: { ideal: SAMPLE_RATE },
    },
    system_processing: "unverified",
  };
}

export function quantizeS16(value) {
  if (!Number.isFinite(value)) return 0;
  const clamped = value < -1 ? -1 : value > 1 ? 1 : value;
  return Math.round(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
}

export function float32ToPcm16(samples) {
  const output = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    output[index] = quantizeS16(samples[index]);
  }
  return output;
}

function writeAscii(view, offset, text) {
  for (let index = 0; index < text.length; index += 1) {
    view.setUint8(offset + index, text.charCodeAt(index));
  }
}

/** Encode one Int16Array, or an array of chunks, as a canonical little-endian WAV. */
export function encodeWav(pcm, { sampleRate = SAMPLE_RATE, channels = CHANNELS } = {}) {
  const chunks = Array.isArray(pcm) ? pcm : [pcm];
  if (!chunks.length || !chunks.every((chunk) => chunk instanceof Int16Array)) {
    throw captureError("invalid-pcm");
  }
  if (channels !== CHANNELS || sampleRate !== SAMPLE_RATE) throw captureError("invalid-pcm");
  let frames = 0;
  for (const chunk of chunks) frames += chunk.length;
  const dataBytes = frames * 2 * channels;
  if (WAV_HEADER_BYTES + dataBytes > MAX_AUDIO_BYTES) throw captureError("audio-limit");
  if (!frames) throw captureError("no-audio");

  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);
  const output = new Uint8Array(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, dataBytes, true);
  let offset = WAV_HEADER_BYTES;
  for (const chunk of chunks) {
    for (const sample of chunk) {
      view.setInt16(offset, sample, true);
      offset += 2;
    }
  }
  return output;
}

export function bytesToBase64(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (let offset = 0; offset < view.length; offset += 0x8000) {
    binary += String.fromCharCode(...view.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

/**
 * onChunk({samples, frameCount, totalFrames, sampleRate, channels,
 * sampleFormat}) receives the same S16 bytes used in the WAV. onLevel gets a
 * 0..1 peak. onStopped(result, "manual" | "limit") runs only after a complete
 * WAV exists; onError runs on interruption and never leaves a partial take.
 */
export function createPcmCapture({ onChunk, onLevel, onError, onStopped } = {}) {
  let phase = "idle";
  let disposed = false;
  let epoch = 0;
  let stream = null;
  let track = null;
  let context = null;
  let source = null;
  let node = null;
  let workletUrl = null;
  let chunks = [];
  let totalFrames = 0;
  let capturedAt = null;
  let settings = null;
  let support = null;
  let result = null;
  let stopPromise = null;
  let limitReached = false;
  let ackWaiter = null;
  let ackTimer = null;

  const emit = (callback, ...args) => {
    try { callback?.(...args); } catch (error) { console.error("EDTH PCM callback failed:", error); }
  };

  function settleAck(error) {
    if (ackTimer !== null) {
      clearTimeout(ackTimer);
      ackTimer = null;
    }
    const waiter = ackWaiter;
    ackWaiter = null;
    if (!waiter) return;
    if (error) waiter.reject(error);
    else waiter.resolve();
  }

  function armStopAck() {
    if (ackWaiter) return ackWaiter.promise;
    let resolve;
    let reject;
    const promise = new Promise((accept, refuse) => {
      resolve = accept;
      reject = refuse;
    });
    ackWaiter = { promise, resolve, reject };
    ackTimer = setTimeout(() => settleAck(captureError("stop-timeout")), STOP_ACK_TIMEOUT_MS);
    return promise;
  }

  function release() {
    settleAck(captureError("audio-interrupted"));
    if (track) { track.onended = null; track.onmute = null; }
    if (context) context.onstatechange = null;
    if (node) { node.port.onmessage = null; node.onprocessorerror = null; }
    try { source?.disconnect(); } catch { /* already gone */ }
    try { node?.disconnect(); } catch { /* already gone */ }
    try { stream?.getTracks().forEach((item) => item.stop()); } catch { /* already gone */ }
    if (workletUrl) {
      try { URL.revokeObjectURL(workletUrl); } catch { /* ignore */ }
      workletUrl = null;
    }
    if (context && context.state !== "closed") {
      try { Promise.resolve(context.close()).catch(() => {}); } catch { /* ignore */ }
    }
    source = node = context = track = stream = null;
  }

  function fail(error) {
    if (phase === "error" || phase === "stopped" || phase === "disposed") return;
    const notify = phase === "recording" || phase === "stopping";
    phase = "error";
    epoch += 1;
    chunks = [];
    totalFrames = 0;
    settings = null;
    capturedAt = null;
    settleAck(error);
    release();
    if (notify) emit(onError, error);
  }

  function handleMessage(event) {
    if (event.data && event.data.type === "stopped") {
      settleAck();
      return;
    }
    if (phase !== "recording" && phase !== "stopping") return;
    let frame;
    try { frame = new Float32Array(event.data); } catch (error) {
      fail(captureError("audio-interrupted", error));
      return;
    }
    if (!frame.length) return;
    const remaining = MAX_FRAMES - totalFrames;
    if (remaining > 0) {
      const pcm = float32ToPcm16(frame.subarray(0, Math.min(frame.length, remaining)));
      chunks.push(pcm);
      totalFrames += pcm.length;
      let peak = 0;
      for (const value of frame) peak = Math.max(peak, Math.abs(value));
      emit(onLevel, Math.min(1, peak));
      emit(onChunk, {
        samples: pcm.slice(),
        frameCount: pcm.length,
        totalFrames,
        sampleRate: SAMPLE_RATE,
        channels: CHANNELS,
        sampleFormat: SAMPLE_FORMAT,
      });
    }
    if (totalFrames >= MAX_FRAMES && !limitReached) {
      limitReached = true;
      void stop("limit");
    }
  }

  async function start() {
    if (disposed) throw captureError("disposed");
    if (phase === "starting" || phase === "recording" || phase === "stopping") {
      throw captureError("busy");
    }
    if (phase === "error" || phase === "stopped") {
      chunks = []; totalFrames = 0; settings = null; capturedAt = null;
      result = null; stopPromise = null; limitReached = false;
    }
    requireApi();
    support = getCaptureSupport();
    const token = ++epoch;
    phase = "starting";
    const cancelled = () => disposed || token !== epoch;
    try {
      const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
      try {
        context = new AudioContextClass({ sampleRate: SAMPLE_RATE, latencyHint: "interactive" });
      } catch (error) { throw captureError("context-unsupported", error); }
      if (context.sampleRate !== SAMPLE_RATE) throw captureError("sample-rate-mismatch");
      if (context.state !== "running") context.resume().catch(() => {});
      let pending;
      try {
        pending = await navigator.mediaDevices.getUserMedia({
          audio: support.contract.constraints,
          video: false,
        });
      } catch (error) { throw microphoneError(error); }
      if (cancelled()) {
        pending.getTracks().forEach((item) => item.stop());
        throw captureError("cancelled");
      }
      stream = pending;
      const tracks = stream.getAudioTracks();
      if (tracks.length !== 1 || stream.getVideoTracks().length) {
        throw captureError("track-unavailable");
      }
      track = tracks[0];
      verifyTrack(track, support);
      if (context.state !== "running") {
        try { await context.resume(); } catch (error) {
          throw captureError("context-unsupported", error);
        }
      }
      if (cancelled()) throw captureError("cancelled");
      if (context.state !== "running") throw captureError("context-unsupported");
      capturedAt = new Date().toISOString();
      settings = buildCaptureSettings({
        track,
        ...support,
        userAgent: globalThis.navigator?.userAgent || "",
      });
      source = context.createMediaStreamSource(stream);
      workletUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "text/javascript" }));
      try {
        await context.audioWorklet.addModule(workletUrl);
      } catch (error) { throw captureError("worklet-failed", error); } finally {
        URL.revokeObjectURL(workletUrl);
        workletUrl = null;
      }
      if (cancelled()) throw captureError("cancelled");
      node = new AudioWorkletNode(context, WORKLET_NAME, {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [CHANNELS],
        channelCountMode: "max",
        channelInterpretation: "discrete",
      });
      node.port.onmessage = handleMessage;
      node.onprocessorerror = () => fail(captureError("audio-interrupted"));
      source.connect(node);
      node.connect(context.destination);
      track.onended = () => fail(captureError("audio-interrupted"));
      track.onmute = () => fail(captureError("audio-interrupted"));
      context.onstatechange = () => {
        if (context && context.state !== "running") {
          fail(captureError("audio-interrupted"));
        }
      };
      if (cancelled()) throw captureError("cancelled");
      phase = "recording";
      return { capturedAt, captureSettings: settings };
    } catch (error) {
      if (phase !== "disposed" && phase !== "stopped") {
        phase = "error";
        epoch += 1;
        release();
      }
      throw error;
    }
  }

  function stop(reason = "manual") {
    if (stopPromise) return stopPromise;
    if (phase === "idle" || phase === "disposed" || phase === "error") {
      return Promise.resolve(null);
    }
    if (phase === "stopped") return Promise.resolve(result);
    if (phase === "starting") {
      phase = "stopped";
      epoch += 1;
      release();
      stopPromise = Promise.resolve(null);
      return stopPromise;
    }
    stopPromise = (async () => {
      phase = "stopping";
      const token = ++epoch;
      try {
        if (!node?.port) throw captureError("audio-interrupted");
        const ack = armStopAck();
        try { node.port.postMessage({ type: "stop" }); } catch (error) {
          settleAck(captureError("worklet-failed", error));
        }
        await ack;
        if (disposed || token !== epoch || phase !== "stopping") return null;
        try { source?.disconnect(); } catch { /* already gone */ }
        try { node?.disconnect(); } catch { /* already gone */ }
        const finalSettings = verifyTrack(track, support);
        if (SUPPORTED_PROCESSING_FLAGS.some((flag) =>
          finalSettings[flag] !== settings.track_settings[flag])
          || finalSettings.channelCount !== settings.track_settings.channelCount) {
          throw captureError("audio-interrupted");
        }
        if (!totalFrames) throw captureError("no-audio");
        const wav = encodeWav(chunks, { sampleRate: SAMPLE_RATE, channels: CHANNELS });
        result = {
          audioBase64: bytesToBase64(wav),
          wavBytes: wav,
          frameCount: totalFrames,
          sampleRate: SAMPLE_RATE,
          channels: CHANNELS,
          channelSelection: "first",
          sampleFormat: SAMPLE_FORMAT,
          durationSeconds: totalFrames / SAMPLE_RATE,
          capturedAt,
          captureSettings: settings,
          hitLimit: limitReached || reason === "limit",
        };
        if (track) { track.onended = null; track.onmute = null; }
        if (context) context.onstatechange = null;
        release();
        phase = "stopped";
        emit(onStopped, result, reason);
        return result;
      } catch (error) {
        if (phase === "stopping") {
          phase = "error";
          chunks = [];
          totalFrames = 0;
          settings = null;
          capturedAt = null;
          release();
          emit(onError, error);
        }
        return null;
      }
    })();
    return stopPromise;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    epoch += 1;
    if (phase !== "stopped" && phase !== "error") phase = "disposed";
    chunks = [];
    totalFrames = 0;
    settings = null;
    capturedAt = null;
    result = null;
    stopPromise = null;
    settleAck(captureError("cancelled"));
    release();
  }

  return { start, stop, dispose };
}
