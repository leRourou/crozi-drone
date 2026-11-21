import { describe, expect, it, vi } from "vitest";
import { type SentinelLike, ScreenWakeLock } from "./wakelock";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

class FakeSentinel implements SentinelLike {
  released = false;
  onrelease: ((event: Event) => void) | null = null;
  async release(): Promise<void> {
    this.released = true;
  }
  /** Le système retire le verrou (page masquée, économie d'énergie). */
  systemRelease(): void {
    this.released = true;
    this.onrelease?.(new Event("release"));
  }
}

function setup({ supported = true } = {}) {
  const sentinels: FakeSentinel[] = [];
  const pending: { resolve: () => void; reject: (e: unknown) => void }[] = [];
  const logs: { text: string; level: string }[] = [];
  let visible = () => {};
  const request = vi.fn(
    (type: "screen") =>
      new Promise<SentinelLike>((resolve, reject) => {
        expect(type).toBe("screen");
        pending.push({
          resolve: () => {
            const s = new FakeSentinel();
            sentinels.push(s);
            resolve(s);
          },
          reject,
        });
      }),
  );
  const lock = new ScreenWakeLock({
    request: supported ? request : undefined,
    onVisible: (cb) => {
      visible = cb;
    },
    log: (text, level = "info") => logs.push({ text, level }),
  });
  const grant = async (i = pending.length - 1) => {
    pending[i].resolve();
    await tick();
  };
  return { lock, request, sentinels, pending, logs, grant, becomeVisible: () => visible() };
}

describe("ScreenWakeLock", () => {
  it("holds a screen lock while recording and logs it", async () => {
    const env = setup();
    env.lock.hold();
    await env.grant();
    expect(env.request).toHaveBeenCalledTimes(1);
    expect(env.logs).toEqual([{ text: "wake lock actif : l'écran reste allumé", level: "info" }]);
  });

  it("asks only once when held twice", async () => {
    const env = setup();
    env.lock.hold();
    env.lock.hold();
    await env.grant();
    expect(env.request).toHaveBeenCalledTimes(1);
  });

  it("does not ask twice when the page becomes visible during a pending request", async () => {
    const env = setup();
    env.lock.hold();
    env.becomeVisible();
    expect(env.request).toHaveBeenCalledTimes(1);
  });

  it("a late release event from an old lock does not forget the current one", async () => {
    const env = setup();
    env.lock.hold();
    await env.grant();
    env.lock.release();
    env.lock.hold();
    await env.grant();
    env.sentinels[0].systemRelease(); // événement du premier verrou, arrivé en retard
    env.becomeVisible();
    expect(env.request).toHaveBeenCalledTimes(2);
  });

  it("gives the lock back on release", async () => {
    const env = setup();
    env.lock.hold();
    await env.grant();
    env.lock.release();
    expect(env.sentinels[0].released).toBe(true);
  });

  it("gives back a lock granted after release was requested", async () => {
    const env = setup();
    env.lock.hold();
    env.lock.release();
    await env.grant();
    expect(env.sentinels[0].released).toBe(true);
    expect(env.logs).toEqual([]);
  });

  it("asks again when the page becomes visible after the system dropped the lock", async () => {
    const env = setup();
    env.lock.hold();
    await env.grant();
    env.becomeVisible(); // verrou encore tenu : rien à faire
    expect(env.request).toHaveBeenCalledTimes(1);
    env.sentinels[0].systemRelease();
    env.becomeVisible();
    await env.grant();
    expect(env.request).toHaveBeenCalledTimes(2);
  });

  it("does not ask again on visibility once released", async () => {
    const env = setup();
    env.lock.hold();
    await env.grant();
    env.lock.release();
    env.becomeVisible();
    expect(env.request).toHaveBeenCalledTimes(1);
  });

  it("warns without blocking when the browser has no Wake Lock API", () => {
    const env = setup({ supported: false });
    expect(() => env.lock.hold()).not.toThrow();
    expect(env.logs).toEqual([
      { text: "wake lock indisponible : l'écran peut s'éteindre pendant l'enregistrement", level: "warn" },
    ]);
  });

  it("warns with the reason when the lock is refused, and can ask again later", async () => {
    const env = setup();
    env.lock.hold();
    env.pending[0].reject(new DOMException("battery saver", "NotAllowedError"));
    await tick();
    expect(env.logs).toEqual([{ text: "wake lock refusé : NotAllowedError battery saver", level: "warn" }]);
    env.becomeVisible();
    expect(env.request).toHaveBeenCalledTimes(2);
  });
});
