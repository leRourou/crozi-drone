import type { ReactNode } from "react";
import {
  ageText,
  altitudeText,
  detectionText,
  droneStatusText,
  levelText,
  listeningText,
  metres,
  rangeText,
  shortName,
  shortStatus,
  statusLabel,
  trackBadge,
  truthErrorText,
  zoneText,
} from "./format";
import { type Listening, listening } from "./mapgeom";
import type { Selection } from "./MapView";
import type { DroneView, EstimatorName, PhoneState, StateMessage } from "./state";

interface Props {
  state: StateMessage;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}

const LISTENING_TONE: Record<Listening, string> = { on: "ok", degraded: "warn", off: "off", never: "off" };

function StatusBadge({ phone, long = false }: { phone: PhoneState; long?: boolean }) {
  const tone = LISTENING_TONE[listening(phone.status)];
  return (
    <span className={`badge ${tone}`}>
      <span className={`dot ${tone}`} aria-hidden="true" />
      {long ? statusLabel(phone.status) : shortStatus(phone.status)}
    </span>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function Head({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="panel-head">
      <h2 className="title">{title}</h2>
      {children}
    </header>
  );
}

function TrackCard({ state }: { state: StateMessage }) {
  const drone = state.drone;
  if (drone?.zone) {
    return (
      <>
        <div className="figures">
          <div><span className="label">Zone</span><span className="data-xl">± {metres(drone.zone.radius_m)}</span></div>
          <div><span className="label">Altitude</span><span className="data-xl">{metres(drone.zone.z_m)}</span></div>
        </div>
        <div className="footer">
          <span className="data-sm">{drone.detecting}/{state.phones.length} capteurs combinés</span>
          <span className="grow" />
          <span className="data-sm muted">{ageText(drone.age_s)}</span>
        </div>
      </>
    );
  }
  return (
    <>
      {drone && (
        <div className="footer">
          <span className="data-xl">{drone.detecting}/{state.phones.length}</span>
          <span className="label">Capteurs en détection</span>
        </div>
      )}
      <p>{droneStatusText(drone, state.estimator)}</p>
    </>
  );
}

function PhoneDetails({ phone, estimator }: { phone: PhoneState; estimator: EstimatorName }) {
  const live = phone.status === "streaming" || phone.status === "stale";
  return (
    <dl className="kv">
      <Row label="Écoute"><StatusBadge phone={phone} long /></Row>
      <Row label="Activité">{ageText(phone.last_seen_age_s)}</Row>
      {live && <Row label="Niveau">{levelText(phone.rms_dbfs)}</Row>}
      {live && <Row label="Temps réel">{phone.rt_ratio === null ? "—" : phone.rt_ratio.toFixed(2).replace(".", ",")}</Row>}
      <Row label="Détection">
        <span className={phone.detection && !phone.detection.fresh ? "old" : ""}>{detectionText(phone.detection, estimator)}</span>
      </Row>
      {phone.detection && <Row label="Âge détection">{ageText(phone.detection.age_s)}</Row>}
      <Row label="Position">
        x {metres(phone.position_m.x)} · y {metres(phone.position_m.y)} · z {metres(phone.position_m.z)}
      </Row>
      {phone.contract && <Row label="Contrat">{phone.contract}</Row>}
    </dl>
  );
}

function DroneDetails({ drone, estimator }: { drone: DroneView | null; estimator: EstimatorName }) {
  const error = drone && truthErrorText(drone);
  return (
    <>
      <dl className="kv">
        <Row label="État">{droneStatusText(drone, estimator)}</Row>
        {drone?.zone && <Row label="Position">{zoneText(drone.zone)}</Row>}
        {drone?.zone && <Row label="Altitude">{altitudeText(drone.zone)}</Row>}
        {drone?.zone && (
          <Row label="Tolérance">
            ± {Math.round(drone.zone.tolerance * 100)} %{drone.zone.degraded ? " (élargie : mesures peu cohérentes)" : ""}
          </Row>
        )}
        {drone && <Row label="Calculé">{ageText(drone.age_s)}</Row>}
      </dl>
      {drone?.truth && (
        <div className="sim-block">
          <span className="label">Vérité simulation</span>
          <dl className="kv">
            <Row label="Position vraie">
              x {metres(drone.truth.x_m)} · y {metres(drone.truth.y_m)} · z {metres(drone.truth.z_m)}
            </Row>
            {error && <Row label="Écart calcul">{error}</Row>}
          </dl>
        </div>
      )}
    </>
  );
}

export function Panel({ state, selected, onSelect }: Props) {
  const selectedPhone = selected?.kind === "phone" ? state.phones.find((p) => p.profile === selected.profile) : undefined;
  const badge = trackBadge(state.drone, state.estimator);
  const close = (
    <button type="button" className="btn" onClick={() => onSelect(null)}>
      Fermer
    </button>
  );
  return (
    <aside className="panel">
      <section aria-label="Piste">
        <Head title={state.drone?.zone ? "Piste T-01" : "Piste"}>
          <span className={`badge ${badge.tone}`}>{badge.text}</span>
        </Head>
        <button
          type="button"
          className={`track-card drone-summary ${selected?.kind === "drone" ? "selected-row" : ""}`}
          aria-pressed={selected?.kind === "drone"}
          onClick={() => onSelect({ kind: "drone" })}
        >
          <TrackCard state={state} />
        </button>
      </section>

      <section aria-label="Capteurs">
        <Head title="Capteurs">
          <span className="data-sm muted">{listeningText(state.phones)}</span>
        </Head>
        <div className="sensors-head" aria-hidden="true">
          <span className="label">ID</span>
          <span className="label">État</span>
          <span className="label">Distance</span>
        </div>
        <ul className="sensors">
          {state.phones.map((phone) => (
            <li key={phone.profile}>
              <button
                type="button"
                className={`sensor-row phone-item ${selectedPhone === phone ? "selected-row" : ""}`}
                aria-pressed={selectedPhone === phone}
                aria-label={`${phone.label} : ${statusLabel(phone.status)}, ${detectionText(phone.detection, state.estimator)}`}
                data-profile={phone.profile}
                data-status={phone.status}
                onClick={() => onSelect({ kind: "phone", profile: phone.profile })}
              >
                <span className="id">{shortName(phone.label)}</span>
                <span><StatusBadge phone={phone} /></span>
                <span className={`detection ${phone.detection?.drone ? "drone" : "muted"} ${phone.detection?.fresh === false ? "old" : ""}`}>
                  {rangeText(phone.detection, state.estimator)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {selectedPhone && (
        <section aria-label={`Détails : ${selectedPhone.label}`}>
          <Head title={`Détail · ${shortName(selectedPhone.label)}`}>{close}</Head>
          <div className="details-body"><PhoneDetails phone={selectedPhone} estimator={state.estimator} /></div>
        </section>
      )}
      {selected?.kind === "drone" && (
        <section aria-label="Détails : drone">
          <Head title={state.drone?.zone ? "Détail · T-01" : "Détail · drone"}>{close}</Head>
          <div className="details-body"><DroneDetails drone={state.drone} estimator={state.estimator} /></div>
        </section>
      )}
      {!selected && <p className="hint">Sélectionnez un capteur ou la piste, ici ou sur le plan.</p>}
    </aside>
  );
}
