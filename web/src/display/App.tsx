import { useEffect, useState } from "react";
import { socketUrl } from "../shared/net";
import { ageText, detectionText, levelText, statusLabel } from "./format";
import type { EstimatorName, PhoneState, StateMessage } from "./state";
import { type Connection, StateClient } from "./stateclient";

const CONNECTION_TEXT: Record<Connection, string> = {
  connecting: "Connexion au serveur…",
  connected: "Connecté",
  reconnecting: "Serveur injoignable",
  invalid: "Message d'état invalide (versions front/serveur différentes ?)",
};

function PhoneCard({ phone, estimator }: { phone: PhoneState; estimator: EstimatorName }) {
  const detection = phone.detection;
  const live = phone.status === "streaming" || phone.status === "stale";
  return (
    <article className={`phone ${phone.status}`} data-profile={phone.profile} data-status={phone.status}>
      <header>
        <h2>{phone.label}</h2>
        <span className="badge">{statusLabel(phone.status)}</span>
      </header>
      <p className={`detection ${detection?.drone ? "drone" : ""} ${detection && !detection.fresh ? "old" : ""}`}>
        {detectionText(detection, estimator)}
        {detection && !detection.fresh && <small> ({ageText(detection.age_s)})</small>}
      </p>
      <dl>
        <dt>Dernière activité</dt>
        <dd>{ageText(phone.last_seen_age_s)}</dd>
        {live && (
          <>
            <dt>Niveau</dt>
            <dd>{levelText(phone.rms_dbfs)}</dd>
            <dt>Temps réel</dt>
            <dd>{phone.rt_ratio === null ? "—" : phone.rt_ratio.toFixed(2)}</dd>
          </>
        )}
        <dt>Position</dt>
        <dd>
          {phone.position_m.x} ; {phone.position_m.y} ; {phone.position_m.z} m
        </dd>
      </dl>
    </article>
  );
}

export function App() {
  const [state, setState] = useState<StateMessage | null>(null);
  const [connection, setConnection] = useState<{ value: Connection; retryInMs?: number }>({ value: "connecting" });

  useEffect(() => {
    const client = new StateClient(
      {
        url: socketUrl("/ws/state"),
        openSocket: (url) => new WebSocket(url),
        setTimer: (fn, ms) => window.setTimeout(fn, ms),
        clearTimer: (id) => window.clearTimeout(id as number),
      },
      { state: setState, connection: (value, retryInMs) => setConnection({ value, retryInMs }) },
    );
    client.start();
    return () => client.stop();
  }, []);

  const offline = connection.value !== "connected";
  return (
    <main className="display">
      <header>
        <h1>Crozidrone · état</h1>
        <span className={`connection ${connection.value}`}>
          {CONNECTION_TEXT[connection.value]}
          {connection.retryInMs !== undefined && ` · nouvel essai dans ${connection.retryInMs / 1000} s`}
        </span>
      </header>
      {state?.estimator === "scripted" && (
        <p className="warning">Estimateur simulé : drone virtuel sur une trajectoire scriptée, pas de vraie détection.</p>
      )}
      {state === null ? (
        <p className="muted">En attente du premier état…</p>
      ) : (
        <section className={`phones ${offline ? "frozen" : ""}`}>
          {state.phones.map((phone) => (
            <PhoneCard key={phone.profile} phone={phone} estimator={state.estimator} />
          ))}
        </section>
      )}
    </main>
  );
}
