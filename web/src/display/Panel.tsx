import type { ReactNode } from "react";
import {
  ageText,
  altitudeText,
  detectionText,
  droneStatusText,
  levelText,
  metres,
  statusLabel,
  speedText,
  truthErrorText,
  zoneText,
} from "./format";
import { Glyph } from "./icons";
import { listening } from "./mapgeom";
import type { Selection } from "./MapView";
import type { DroneView, EstimatorName, PhoneState, StateMessage } from "./state";

interface Props {
  state: StateMessage;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function PhoneDetails({ phone, estimator }: { phone: PhoneState; estimator: EstimatorName }) {
  const live = phone.status === "streaming" || phone.status === "stale";
  return (
    <section className="details" aria-label={`Détails : ${phone.label}`}>
      <h2>
        <Glyph kind="phone" /> {phone.label}
      </h2>
      <dl>
        <Row label="Écoute">
          <span className={`listening ${listening(phone.status)}`}>{statusLabel(phone.status)}</span>
        </Row>
        <Row label="Dernière activité">{ageText(phone.last_seen_age_s)}</Row>
        {live && <Row label="Niveau">{levelText(phone.rms_dbfs)}</Row>}
        {live && <Row label="Temps réel">{phone.rt_ratio === null ? "—" : phone.rt_ratio.toFixed(2)}</Row>}
        <Row label="Détection">
          <span className={phone.detection && !phone.detection.fresh ? "old" : ""}>
            {detectionText(phone.detection, estimator)}
          </span>
        </Row>
        {phone.detection && <Row label="Âge de la détection">{ageText(phone.detection.age_s)}</Row>}
        <Row label="Position">
          x {metres(phone.position_m.x)} · y {metres(phone.position_m.y)} · z {metres(phone.position_m.z)}
        </Row>
        {phone.contract && <Row label="Contrat">{phone.contract}</Row>}
      </dl>
    </section>
  );
}

function DroneDetails({ drone, estimator }: { drone: DroneView | null; estimator: EstimatorName }) {
  const truth = drone?.truth ?? null;
  const trackError = truthErrorText(truth, drone?.track ?? null);
  const zoneError = truthErrorText(truth, drone?.zone ?? null);
  return (
    <section className="details" aria-label="Détails : drone">
      <h2>
        <Glyph kind="drone" /> Drone
      </h2>
      <dl>
        <Row label="État">{droneStatusText(drone, estimator)}</Row>
        {drone?.track && <Row label="Position filtrée">{zoneText(drone.track)}</Row>}
        {drone?.track && <Row label="Altitude filtrée">{altitudeText(drone.track)}</Row>}
        {drone?.track && <Row label="Vitesse">{speedText(drone.track)}</Row>}
        {drone?.zone && <Row label="Position brute">{zoneText(drone.zone)}</Row>}
        {drone?.zone && <Row label="Altitude">{altitudeText(drone.zone)}</Row>}
        {drone?.zone && (
          <Row label="Tolérance">
            ± {Math.round(drone.zone.tolerance * 100)} %{drone.zone.degraded ? " (élargie : mesures peu cohérentes)" : ""}
          </Row>
        )}
        {drone && <Row label="Calculé">{ageText(drone.age_s)}</Row>}
        {drone?.truth && (
          <Row label="Position simulée">
            x {metres(drone.truth.x_m)} · y {metres(drone.truth.y_m)} · z {metres(drone.truth.z_m)}
          </Row>
        )}
        {trackError && <Row label="Écart filtré / simulé">{trackError}</Row>}
        {zoneError && <Row label="Écart brut / simulé">{zoneError}</Row>}
      </dl>
    </section>
  );
}

function Legend() {
  return (
    <ul className="legend">
      <li><Glyph kind="phone" size={18} /> Téléphone</li>
      <li><Glyph kind="phone-detecting" size={18} /> Téléphone qui détecte</li>
      <li><Glyph kind="drone" size={18} /> Drone (calculé)</li>
      <li><Glyph kind="ghost" size={18} /> Drone simulé (réel)</li>
      <li><span className="swatch ring" /> Distance ± marge</li>
      <li><span className="swatch structure" /> Structure</li>
    </ul>
  );
}

export function Panel({ state, selected, onSelect }: Props) {
  const selectedPhone = selected?.kind === "phone" ? state.phones.find((p) => p.profile === selected.profile) : undefined;
  return (
    <aside className="panel">
      <button
        type="button"
        className={`drone-summary ${selected?.kind === "drone" ? "selected" : ""}`}
        onClick={() => onSelect({ kind: "drone" })}
      >
        <Glyph kind="drone" /> {droneStatusText(state.drone, state.estimator)}
      </button>
      <ul className="phone-list">
        {state.phones.map((phone) => (
          <li key={phone.profile}>
            <button
              type="button"
              className={`phone-item ${selectedPhone === phone ? "selected" : ""}`}
              data-profile={phone.profile}
              data-status={phone.status}
              onClick={() => onSelect({ kind: "phone", profile: phone.profile })}
            >
              <span className={`listening-dot ${listening(phone.status)}`} aria-hidden="true" />
              <span className="name">{phone.label}</span>
              <span className="status">{statusLabel(phone.status)}</span>
              <span className="detection">{detectionText(phone.detection, state.estimator)}</span>
            </button>
          </li>
        ))}
      </ul>
      {selectedPhone && <PhoneDetails phone={selectedPhone} estimator={state.estimator} />}
      {selected?.kind === "drone" && <DroneDetails drone={state.drone} estimator={state.estimator} />}
      {!selected && <p className="hint">Cliquez sur un téléphone ou sur le drone pour voir le détail.</p>}
      <Legend />
    </aside>
  );
}
