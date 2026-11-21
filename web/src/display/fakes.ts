/** Messages d'état de test (Vitest uniquement), conformes à docs/protocol.md. */

export function phone(overrides: Record<string, unknown> = {}) {
  return {
    profile: "noe",
    label: "Téléphone de Noé",
    position_m: { x: 2.06, y: 9.66, z: 0 },
    status: "streaming",
    session_id: "sid",
    contract: "edth.web-pcm.v1",
    last_seen_age_s: 0.04,
    rt_ratio: 1.0,
    rms_dbfs: -42.1,
    detection: { drone: true, distance_m: 12.3, uncertainty_rel: 0.1, age_s: 0.4, fresh: true },
    ...overrides,
  };
}

export function message(overrides: Record<string, unknown> = {}) {
  return { type: "state", server_time: 1795000000, estimator: "scripted", drone: null, phones: [phone()], ...overrides };
}

export function droneView(overrides: Record<string, unknown> = {}) {
  return {
    status: "located",
    detecting: 3,
    zone: { x_m: 3.1, y_m: 7.9, radius_m: 0.8, z_m: 1.4, z_min_m: 1.1, z_max_m: 1.7, tolerance: 0.1, degraded: false },
    track: { x_m: 3.0, y_m: 8.1, z_m: 1.5, vx_mps: 0.3, vy_mps: -0.4, radius_m: 0.4, z_min_m: 1.2, z_max_m: 1.8 },
    truth: { x_m: 3.0, y_m: 8.0, z_m: 1.5 },
    age_s: 0.1,
    ...overrides,
  };
}
