import { useEffect, useState } from "react";
import { socketUrl } from "../shared/net";
import { MapView, type Selection } from "./MapView";
import { Panel } from "./Panel";
import type { StateMessage } from "./state";
import { type Connection, StateClient } from "./stateclient";

const CONNECTION_TEXT: Record<Connection, string> = {
  connecting: "Connexion au serveur…",
  connected: "Connecté",
  reconnecting: "Serveur injoignable",
  invalid: "Message d'état invalide (versions front/serveur différentes ?)",
};

export function App() {
  const [state, setState] = useState<StateMessage | null>(null);
  const [connection, setConnection] = useState<{ value: Connection; retryInMs?: number }>({ value: "connecting" });
  const [selected, setSelected] = useState<Selection>(null);

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
        <h1>Plan de salle · positionnement</h1>
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
        <div className={`layout ${offline ? "frozen" : ""}`}>
          <MapView state={state} selected={selected} onSelect={setSelected} />
          <Panel state={state} selected={selected} onSelect={setSelected} />
        </div>
      )}
    </main>
  );
}
