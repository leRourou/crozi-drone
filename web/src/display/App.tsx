import { lazy, Suspense, useEffect, useState } from "react";
import { socketUrl } from "../shared/net";
import { MapView } from "./MapView";
import type { Selection } from "./selection";
import { Panel } from "./Panel";
import type { StateMessage } from "./state";
import { type Connection, StateClient } from "./stateclient";

// three.js n'est téléchargé qu'au premier passage en 3D : la page 2D reste légère.
const Map3D = lazy(() => import("./Map3D"));

/** WebGL 2 absent (vieux poste, accélération coupée) : la 3D est proposée désactivée, le 2D reste. */
const HAS_WEBGL = Boolean(document.createElement("canvas").getContext("webgl2"));

type View = "2d" | "3d";

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
  const [view, setView] = useState<View>("2d");

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
          <div className="map-column">
            <div className="view-switch" role="toolbar" aria-label="Vue du plan">
              <button type="button" aria-pressed={view === "2d"} onClick={() => setView("2d")}>2D</button>
              <button type="button" aria-pressed={view === "3d"} onClick={() => setView("3d")} disabled={!HAS_WEBGL}
                title={HAS_WEBGL ? undefined : "WebGL 2 indisponible dans ce navigateur"}>3D</button>
            </div>
            {view === "2d" ? (
              <MapView state={state} selected={selected} onSelect={setSelected} />
            ) : (
              <Suspense fallback={<p className="muted">Chargement de la vue 3D…</p>}>
                <Map3D state={state} selected={selected} onSelect={setSelected} />
              </Suspense>
            )}
          </div>
          <Panel state={state} selected={selected} onSelect={setSelected} />
        </div>
      )}
    </main>
  );
}
