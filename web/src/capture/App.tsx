import { createPcmCapture, getCaptureSupport, WEBKIT_CAPTURE_CONTRACT } from "@edth/capture";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { appendLog, clock, type LogLine } from "./logbuffer";
import { isLittleEndian } from "./packetizer";
import { PROFILES, type ProfileId } from "./profiles";
import { type LogLevel, type Status, Streamer, subtleSha256Hex } from "./streamer";

function socketUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/audio`;
}

function expectedContract(): { text: string; webkit: boolean } {
  try {
    const { contract } = getCaptureSupport();
    return { text: contract.id, webkit: contract.id === WEBKIT_CAPTURE_CONTRACT.id };
  } catch (error) {
    return { text: `navigateur non conforme (${(error as { code?: string }).code})`, webkit: false };
  }
}

const WEBKIT_WARNING =
  "Profil WebKit (iPhone) : seul l'anti-écho est vérifié. Réduction de bruit et gain automatique " +
  "ne sont pas exposés par Safari ; données non équivalentes au profil strict.";

const STATE_LABEL: Record<Status["state"], string> = {
  idle: "Prêt",
  starting: "Connexion…",
  streaming: "Enregistrement",
  error: "Erreur",
};

export function App() {
  const [status, setStatus] = useState<Status>({ state: "idle" });
  const [profile, setProfile] = useState<ProfileId | null>(null); // non mémorisé : à choisir à chaque ouverture
  const [lines, setLines] = useState<LogLine[]>([]);
  const levelRef = useRef<HTMLButtonElement>(null);
  const nextId = useRef(0);
  const expected = useMemo(expectedContract, []);

  const log = useCallback((text: string, level: LogLevel = "info") => {
    const line = { id: nextId.current++, time: clock(new Date()), text, level };
    setLines((current) => appendLog(current, line));
  }, []);

  const streamer = useMemo(
    () =>
      new Streamer(
        {
          createCapture: createPcmCapture,
          openSocket: (url) => new WebSocket(url),
          url: socketUrl(),
          uuid: () => crypto.randomUUID(),
          now: () => performance.now(),
          userAgent: navigator.userAgent,
          littleEndian: isLittleEndian(),
          sha256Hex: subtleSha256Hex,
        },
        {
          log,
          status: setStatus,
          // Mise à jour directe du DOM : ~375 appels/s, inutile de re-rendre React.
          level: (peak) => levelRef.current?.style.setProperty("--level", String(peak)),
        },
      ),
    [log],
  );

  useEffect(() => () => streamer.stop(), [streamer]);

  const running = status.state === "starting" || status.state === "streaming";
  const webkit = status.webkit ?? expected.webkit;
  const lastError = status.state === "error" ? lines.findLast((l) => l.level === "error") : undefined;

  return (
    <main>
      <header>
        <h1>Crozidrone</h1>
        <span className={`badge ${status.state}`}>{STATE_LABEL[status.state]}</span>
      </header>

      <section className="recorder">
        <fieldset className="profiles" disabled={running}>
          <legend>Profil</legend>
          {PROFILES.map((p) => (
            <label key={p.id}>
              <input
                type="radio"
                name="profile"
                value={p.id}
                checked={profile === p.id}
                onChange={() => setProfile(p.id)}
              />
              {p.label}
            </label>
          ))}
        </fieldset>
        <button
          type="button"
          ref={levelRef}
          className={`record ${running ? "on" : ""}`}
          aria-label={running ? "Arrêter" : "Démarrer"}
          disabled={profile === null}
          onClick={() => (running ? streamer.stop() : profile && streamer.start(profile))}
        >
          <span className="icon" />
        </button>
        <p className="hint">
          {running ? "Appuyer pour arrêter" : profile ? "Appuyer pour enregistrer" : "Choisir un profil"}
        </p>
        {lastError && <p className="error">{lastError.text}</p>}
        {webkit && <p className="warning">{WEBKIT_WARNING}</p>}
      </section>

      <details>
        <summary>Détails</summary>
        <dl className="status">
          <dt>Profil</dt>
          <dd>{status.profile ?? profile ?? "—"}</dd>
          <dt>Contrat</dt>
          <dd>{status.contract ?? `${expected.text} (prévu)`}</dd>
          <dt>Session</dt>
          <dd>{status.sessionId?.slice(0, 8) ?? "—"}</dd>
        </dl>
        {/* column-reverse + liste inversée : la plus récente en bas, défilement ancré en bas */}
        <ol className="logs" aria-live="polite">
          {[...lines].reverse().map((line) => (
            <li key={line.id} className={line.level}>
              <time>{line.time}</time> {line.text}
            </li>
          ))}
        </ol>
      </details>
    </main>
  );
}
