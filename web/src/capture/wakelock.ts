/**
 * Garde l'écran allumé pendant un enregistrement (Screen Wake Lock API).
 * Sans effet sur l'audio : si l'API manque ou refuse, on avertit et l'enregistrement continue.
 */
import type { LogLevel } from "./streamer";

/** Sous-ensemble de WakeLockSentinel utilisé ici (remplaçable par une doublure en test). */
export interface SentinelLike {
  release(): Promise<void>;
  onrelease: ((event: Event) => void) | null;
}

export interface WakeLockDeps {
  /** `navigator.wakeLock.request`, ou undefined si le navigateur ne l'expose pas. */
  request: ((type: "screen") => Promise<SentinelLike>) | undefined;
  /** Appelle `callback` chaque fois que la page redevient visible. */
  onVisible: (callback: () => void) => void;
  log: (text: string, level?: LogLevel) => void;
}

export class ScreenWakeLock {
  private wanted = false;
  private requesting = false;
  private sentinel: SentinelLike | null = null;

  constructor(private readonly deps: WakeLockDeps) {
    // Le système retire le verrou quand la page est masquée : on le redemande au retour.
    deps.onVisible(() => {
      if (this.wanted) void this.acquire();
    });
  }

  hold(): void {
    if (this.wanted) return;
    this.wanted = true;
    void this.acquire();
  }

  release(): void {
    this.wanted = false;
    void this.sentinel?.release();
    this.sentinel = null;
  }

  private async acquire(): Promise<void> {
    if (this.sentinel !== null || this.requesting) return;
    const request = this.deps.request;
    if (request === undefined) {
      this.deps.log("wake lock indisponible : l'écran peut s'éteindre pendant l'enregistrement", "warn");
      return;
    }
    this.requesting = true;
    try {
      this.keep(await request("screen"));
    } catch (error) {
      const e = error as Partial<Error>;
      this.deps.log(`wake lock refusé : ${e.name} ${e.message}`, "warn");
    } finally {
      this.requesting = false;
    }
  }

  private keep(sentinel: SentinelLike): void {
    if (!this.wanted) {
      void sentinel.release(); // arrêt demandé pendant la requête
      return;
    }
    this.sentinel = sentinel;
    sentinel.onrelease = () => {
      if (this.sentinel === sentinel) this.sentinel = null;
    };
    this.deps.log("wake lock actif : l'écran reste allumé");
  }
}
