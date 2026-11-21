import { useEffect, useRef, useState } from "react";
import { socketUrl } from "../shared/net";
import { listeningText, metres, trackBadge, utcClock } from "./format";
import { MapLegend, MapView, type Selection } from "./MapView";
import { Panel } from "./Panel";
import { ROOM } from "./room";
import type { StateMessage } from "./state";
import { type Connection, StateClient } from "./stateclient";

const CONNECTION_BADGE: Record<Connection, { text: string; tone: string }> = {
  connecting: { text: "Connexion…", tone: "off" },
  connected: { text: "Live", tone: "ok" },
  reconnecting: { text: "Déconnecté", tone: "off" },
  invalid: { text: "Message invalide", tone: "warn" },
};

function StatusBar({ state, connection }: { state: StateMessage | null; connection: { value: Connection; retryInMs?: number } }) {
  const link = CONNECTION_BADGE[connection.value];
  const badge = state && trackBadge(state.drone, state.estimator);
  return (
    <header className="bar">
      <h1 className="brand">CROZIDRONE</h1>
      <div>
        <span className={`badge connection ${connection.value} ${link.tone}`}>
          <span className={`dot ${link.tone}`} aria-hidden="true" />
          {link.text}
        </span>
        {connection.retryInMs !== undefined && <span className="data-sm muted">nouvel essai dans {connection.retryInMs / 1000} s</span>}
      </div>
      {state && (
        <div>
          <span className="label">Capteurs</span>
          <span className="data-sm">{listeningText(state.phones)}</span>
        </div>
      )}
      {badge && (
        <div>
          <span className="label">Piste</span>
          <span className={`badge ${badge.tone}`}>{badge.text}</span>
        </div>
      )}
      <span className="spacer" />
      {state?.estimator === "scripted" && (
        <div>
          <span className="badge sim">Simulation</span>
          <span className="data-sm dim">trajectoire scriptée, pas de vraie détection</span>
        </div>
      )}
      {state && <time className="clock">{utcClock(state.server_time)}</time>}
    </header>
  );
}

function LinkLost({ state, connection, onRetry }: { state: StateMessage | null; connection: Connection; onRetry: () => void }) {
  const invalid = connection === "invalid";
  return (
    <section className="link-lost" role="alert">
      <h2>{invalid ? "Message d'état invalide" : "Liaison serveur perdue"}</h2>
      <p>
        {invalid && "Versions du front et du serveur différentes ? "}
        {state ? `Le plan montre le dernier état reçu, à ${utcClock(state.server_time)}. Rien n'y est à jour.` : "Aucun état reçu pour l'instant."}
      </p>
      {!invalid && (
        <div className="actions">
          <span className="data-sm muted">Reconnexion automatique en cours</span>
          <span className="grow" />
          <button type="button" className="btn primary" onClick={onRetry}>Réessayer</button>
        </div>
      )}
    </section>
  );
}

export function App() {
  const [state, setState] = useState<StateMessage | null>(null);
  const [connection, setConnection] = useState<{ value: Connection; retryInMs?: number }>({ value: "connecting" });
  const [selected, setSelected] = useState<Selection>(null);
  const client = useRef<StateClient | null>(null);

  useEffect(() => {
    const c = new StateClient(
      {
        url: socketUrl("/ws/state"),
        openSocket: (url) => new WebSocket(url),
        setTimer: (fn, ms) => window.setTimeout(fn, ms),
        clearTimer: (id) => window.clearTimeout(id as number),
      },
      { state: setState, connection: (value, retryInMs) => setConnection({ value, retryInMs }) },
    );
    client.current = c;
    c.start();
    return () => c.stop();
  }, []);

  const lost = connection.value === "reconnecting" || connection.value === "invalid";
  const frozen = connection.value !== "connected" && state !== null;
  return (
    <main className={`display ${frozen ? "frozen" : ""}`}>
      <StatusBar state={state} connection={connection} />
      {state?.estimator === "scripted" && <div className="sim-stripes" aria-hidden="true" />}
      <div className="map-area">
        {state === null ? (
          <p className="waiting">En attente du premier état…</p>
        ) : (
          <div className="map-wrap">
            <MapView state={state} selected={selected} onSelect={setSelected} />
            <div className="heading">
              <span className="title">Plan de salle</span>
              <span className="data-sm muted">{metres(ROOM.width_m)} × {metres(ROOM.height_m)} · carreau 1 m</span>
            </div>
            <MapLegend simulated={state.estimator === "scripted"} />
          </div>
        )}
        {lost && <LinkLost state={state} connection={connection.value} onRetry={() => client.current?.retryNow()} />}
      </div>
      {state && <Panel state={state} selected={selected} onSelect={setSelected} />}
    </main>
  );
}
