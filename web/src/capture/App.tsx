import { createPcmCapture, getCaptureSupport, WEBKIT_CAPTURE_CONTRACT } from "@edth/capture";
import { type FormEvent, type RefObject, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { appendLog, clock, type LogLine } from "./logbuffer";
import { isLittleEndian } from "./packetizer";
import { socketUrl } from "../shared/net";
import { findProfile, PROFILES, type Profile } from "../shared/profiles";
import { type LogLevel, type Status, Streamer, subtleSha256Hex } from "./streamer";
import { ScreenWakeLock } from "./wakelock";

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
  reconnecting: "Reconnexion…",
  streaming: "Enregistrement",
  error: "Erreur",
};

/** Donne le focus au titre de l'étape quand on vient d'y arriver (lecteurs d'écran, clavier). */
function useStepHeading(focus: boolean): RefObject<HTMLHeadingElement | null> {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) ref.current?.focus();
  }, [focus]);
  return ref;
}

function Progress({ step }: { step: 1 | 2 }) {
  return (
    <div className="progress">
      <span>Étape {step} sur 2</span>
      <ol aria-hidden="true">
        <li className="done" />
        <li className={step === 2 ? "done" : ""} />
      </ol>
    </div>
  );
}

interface ProfileStepProps {
  choice?: Profile;
  focus: boolean;
  onChoose: (profile?: Profile) => void;
  onContinue: (profile: Profile) => void;
}

function ProfileStep({ choice, focus, onChoose, onContinue }: ProfileStepProps) {
  const heading = useStepHeading(focus);
  const selectId = useId();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (choice) onContinue(choice);
  };
  return (
    <form className="step" onSubmit={submit}>
      <h2 ref={heading} tabIndex={-1}>
        Quel est ton téléphone&nbsp;?
      </h2>
      <p className="lead">Chaque enregistrement sera rattaché à ce téléphone.</p>
      <div className="field">
        <label htmlFor={selectId}>Téléphone</label>
        <select id={selectId} value={choice?.id ?? ""} onChange={(e) => onChoose(findProfile(e.target.value))} required>
          <option value="" disabled>
            Choisir un profil…
          </option>
          {PROFILES.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      <button type="submit" className="primary" disabled={!choice}>
        Continuer
      </button>
    </form>
  );
}

interface RecordStepProps {
  profile: Profile; // non nul : impossible d'enregistrer sans profil choisi
  running: boolean;
  focus: boolean;
  levelRef: RefObject<HTMLButtonElement | null>;
  error?: string;
  webkit: boolean;
  onToggle: () => void;
  onBack: () => void;
}

function RecordStep({ profile, running, focus, levelRef, error, webkit, onToggle, onBack }: RecordStepProps) {
  const heading = useStepHeading(focus);
  return (
    <section className="step recorder">
      <h2 ref={heading} tabIndex={-1}>
        Enregistrement
      </h2>
      <p className="chip">
        <span className="dot" aria-hidden="true" />
        {profile.label}
        {!running && (
          <button type="button" className="link" onClick={onBack}>
            Changer
          </button>
        )}
      </p>
      <button
        type="button"
        ref={levelRef}
        className={`record ${running ? "on" : ""}`}
        aria-label={running ? "Arrêter" : "Démarrer"}
        onClick={onToggle}
      >
        <span className="icon" />
      </button>
      <p className="hint">{running ? "Appuyer pour arrêter" : "Appuyer pour enregistrer"}</p>
      {error && <p className="error">{error}</p>}
      {webkit && <p className="warning">{WEBKIT_WARNING}</p>}
    </section>
  );
}

export function App() {
  const [status, setStatus] = useState<Status>({ state: "idle" });
  // Non mémorisés : à choisir à chaque ouverture. choice = select, confirmed = étape 2.
  const [choice, setChoice] = useState<Profile>();
  const [confirmed, setConfirmed] = useState<Profile>();
  const [navigated, setNavigated] = useState(false); // pas de vol de focus au chargement
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
          url: socketUrl("/ws/audio"),
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

  const wakeLock = useMemo(
    () =>
      new ScreenWakeLock({
        request: "wakeLock" in navigator ? (type) => navigator.wakeLock.request(type) : undefined,
        onVisible: (callback) =>
          document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible") callback();
          }),
        log,
      }),
    [log],
  );

  const running = status.state === "starting" || status.state === "streaming" || status.state === "reconnecting";

  useEffect(() => {
    if (!running) return;
    wakeLock.hold();
    return () => wakeLock.release();
  }, [running, wakeLock]);
  const webkit = status.webkit ?? expected.webkit;
  const lastError = status.state === "error" ? lines.findLast((l) => l.level === "error") : undefined;
  const goTo = (profile?: Profile) => {
    setNavigated(true);
    setConfirmed(profile);
  };

  return (
    <main>
      <header>
        <h1>Crozidrone</h1>
        <span className={`badge ${status.state}`}>{STATE_LABEL[status.state]}</span>
      </header>

      <Progress step={confirmed ? 2 : 1} />
      {confirmed ? (
        <RecordStep
          profile={confirmed}
          running={running}
          focus={navigated}
          levelRef={levelRef}
          error={lastError?.text}
          webkit={webkit}
          onToggle={() => (running ? streamer.stop() : streamer.start(confirmed.id))}
          onBack={() => goTo(undefined)}
        />
      ) : (
        <ProfileStep choice={choice} focus={navigated} onChoose={setChoice} onContinue={goTo} />
      )}

      <details>
        <summary>Détails</summary>
        <dl className="status">
          <dt>Profil</dt>
          <dd>{status.profile ?? confirmed?.id ?? "—"}</dd>
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
