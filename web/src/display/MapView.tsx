import type { KeyboardEvent, ReactNode } from "react";
import { metres, shortName } from "./format";
import { PX, Reticle, SensorIcon, TrackIcon, TruthIcon } from "./icons";
import { annulusPath, hearsDrone, listening, rangeRings } from "./mapgeom";
import { outlinePath, ROOM } from "./room";
import type { StateMessage } from "./state";

export type Selection = { kind: "phone"; profile: string } | { kind: "drone" } | null;

interface Props {
  state: StateMessage;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}

const MARGIN = { left: 1.1, top: 0.8, right: 0.6, bottom: 1.4 };
const VIEWBOX = [
  -MARGIN.left,
  -MARGIN.top,
  ROOM.width_m + MARGIN.left + MARGIN.right,
  ROOM.height_m + MARGIN.top + MARGIN.bottom,
].join(" ");

function Clickable(props: { label: string; selected: boolean; onSelect: () => void; className: string; x: number; y: number; data?: Record<string, string>; children: ReactNode }) {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      props.onSelect();
    }
  };
  return (
    <g
      className={`${props.className} ${props.selected ? "selected" : ""}`}
      transform={`translate(${props.x} ${props.y}) scale(${PX})`}
      role="button"
      tabIndex={0}
      aria-label={props.label}
      aria-pressed={props.selected}
      onClick={props.onSelect}
      onKeyDown={onKey}
      {...props.data}
    >
      {props.children}
    </g>
  );
}

function Room() {
  const grid = [];
  for (let x = 1; x < ROOM.width_m; x += 1) grid.push(`M${x},0V${ROOM.height_m}`);
  for (let y = 1; y < ROOM.height_m; y += 1) grid.push(`M0,${y}H${ROOM.width_m}`);
  return (
    <g className="room">
      <path d={outlinePath} className="floor" />
      <path d={grid.join("")} className="grid" clipPath="url(#room-clip)" />
      {ROOM.pillars.map((p) => (
        <rect key={p.y} x={p.x} y={p.y} width={p.w} height={p.h} className="pillar" />
      ))}
      <path d={outlinePath} className="walls" />
    </g>
  );
}

/** Carroyage (abscisses tous les 2 m, ordonnées tous les 5 m) et échelle. */
function GridLabels() {
  const xs = [0, 2, 4, 6, 8, 10];
  const ys = [0, 5, 10, 15, 20];
  const h = ROOM.height_m;
  return (
    <g aria-hidden="true">
      <g className="gridlabels">
        {xs.map((x) => (
          <text key={x} x={x} y={-0.25} textAnchor="middle">{x === 10 ? "10 m" : x}</text>
        ))}
        {ys.map((y) => (
          <text key={y} x={-0.25} y={y + 0.09} textAnchor="end">{y === 20 ? "20 m" : y}</text>
        ))}
      </g>
      <g className="scale" transform={`translate(0 ${h + 0.8})`}>
        <path d="M0,-0.15V0.15M0,0H5M5,-0.15V0.15M2.5,-0.08V0.08" />
        <text x={0} y={0.5} textAnchor="middle">0</text>
        <text x={5} y={0.5} textAnchor="middle">5 m</text>
      </g>
    </g>
  );
}

export function MapView({ state, selected, onSelect }: Props) {
  const drone = state.drone;
  const rings = rangeRings(state.phones);
  const droneSelected = selected?.kind === "drone";
  return (
    <svg className="map" viewBox={VIEWBOX} role="img" aria-label="Plan de salle : capteurs et drone">
      <defs>
        <clipPath id="room-clip">
          <path d={outlinePath} />
        </clipPath>
        <pattern id="hatch" width="0.15" height="0.15" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="0.15" height="0.15" className="hatch-bg" />
          <line x1="0" y1="0" x2="0" y2="0.15" className="hatch-line" />
        </pattern>
      </defs>
      <Room />
      <GridLabels />
      <g className="rings" clipPath="url(#room-clip)">
        {rings.map((ring) => (
          <g key={ring.profile} className={`ring ${ring.fresh ? "" : "old"}`} data-ring={ring.profile}>
            <path d={annulusPath(ring.cx, ring.cy, ring.inner, ring.outer)} className="margin" fillRule="evenodd" />
            <circle cx={ring.cx} cy={ring.cy} r={ring.r} className="distance" />
          </g>
        ))}
      </g>
      {drone?.zone && <circle cx={drone.zone.x_m} cy={drone.zone.y_m} r={drone.zone.radius_m} className="zone" />}
      {drone?.truth && (
        <Clickable label="Drone simulé (position vraie)" selected={droneSelected && !drone.zone} onSelect={() => onSelect({ kind: "drone" })} className="drone-marker ghost" x={drone.truth.x_m} y={drone.truth.y_m}>
          <circle r={8} className="hit" />
          <TruthIcon />
          {!drone.zone && <Reticle w={12} h={12} />}
        </Clickable>
      )}
      {/* Piste avant les capteurs : un capteur survolé reste visible et cliquable. */}
      {drone?.zone && (
        <Clickable label="Drone (position calculée)" selected={droneSelected} onSelect={() => onSelect({ kind: "drone" })} className="drone-marker" x={drone.zone.x_m} y={drone.zone.y_m} data={{ "data-drone": "located" }}>
          <TrackIcon />
          <Reticle w={18} h={16} />
          <text className="track-label" y={-22}>{`T-01 · ± ${metres(drone.zone.radius_m)} · z ${metres(drone.zone.z_m)}`}</text>
        </Clickable>
      )}
      {state.phones.map((phone) => {
        const state_ = listening(phone.status);
        const isSelected = selected?.kind === "phone" && selected.profile === phone.profile;
        const detecting = hearsDrone(phone);
        return (
          <Clickable
            key={phone.profile}
            label={`${phone.label} : ${phone.status === "streaming" ? "à l'écoute" : "pas à l'écoute"}${detecting ? ", détecte le drone" : ""}`}
            selected={isSelected}
            onSelect={() => onSelect({ kind: "phone", profile: phone.profile })}
            className={`phone-marker ${state_} ${detecting ? "detecting" : ""}`}
            x={phone.position_m.x}
            y={phone.position_m.y}
            data={{ "data-profile": phone.profile, "data-listening": state_, "data-detecting": String(detecting) }}
          >
            <rect x={-16} y={-12} width={84} height={24} className="hit" />
            <SensorIcon />
            <circle cx={10} cy={-7} r={3} className="pip" />
            <Reticle w={16} h={12} />
            <text className="name" x={20} y={4}>{shortName(phone.label)}</text>
          </Clickable>
        );
      })}
    </svg>
  );
}

/** Légende flottante, en bas à gauche du plan. */
export function MapLegend({ simulated }: { simulated: boolean }) {
  const icon = (children: ReactNode) => (
    <svg width="28" height="18" viewBox="-14 -9 28 18" aria-hidden="true">{children}</svg>
  );
  return (
    <section className="legend" aria-label="Légende">
      <header className="panel-head"><h2 className="label">Légende</h2></header>
      <ul>
        <li>{icon(<SensorIcon />)} Capteur (téléphone), pastille = écoute</li>
        <li>{icon(<g className="detecting"><SensorIcon /></g>)} Capteur qui entend le drone</li>
        <li>
          {icon(
            <g className="ring">
              <path d={annulusPath(0, 0, 8, 13)} className="margin" fillRule="evenodd" />
              <circle r={10.5} className="distance" style={{ strokeWidth: 1, strokeDasharray: "3 2" }} />
            </g>,
          )}{" "}
          Distance mesurée ± marge
        </li>
        <li>{icon(<TrackIcon />)} Piste drone (calculée)</li>
        <li>{icon(<circle r={8} className="zone" style={{ strokeWidth: 1, strokeDasharray: "3 2" }} />)} Zone estimée</li>
        {simulated && <li>{icon(<TruthIcon />)} Position vraie du drone simulé</li>}
      </ul>
    </section>
  );
}
