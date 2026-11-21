import type { KeyboardEvent, ReactNode } from "react";
import { metres } from "./format";
import { DroneIcon, PhoneIcon, PX } from "./icons";
import { annulusPath, hearsDrone, listening, rangeRings } from "./mapgeom";
import { outlinePath, ROOM } from "./room";
import type { StateMessage } from "./state";

export type Selection = { kind: "phone"; profile: string } | { kind: "drone" } | null;

interface Props {
  state: StateMessage;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}

const MARGIN = { left: 2, top: 1.6, right: 2.2, bottom: 2 };
const VIEWBOX = [
  -MARGIN.left,
  -MARGIN.top,
  ROOM.width_m + MARGIN.left + MARGIN.right,
  ROOM.height_m + MARGIN.top + MARGIN.bottom,
].join(" ");
/** Cote du plan : deux décimales, virgule (comme le relevé de la salle). */
const cote = (v: number) => v.toFixed(2).replace(".", ",");

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
      transform={`translate(${props.x} ${props.y})`}
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

function Dimensions() {
  const { width_m: w, height_m: h } = ROOM;
  return (
    <g className="dimensions">
      <path d={`M0,-0.55H${w}M0,-0.7V-0.4M${w},-0.7V-0.4`} />
      <text x={w / 2} y={-0.8} textAnchor="middle">{metres(w)}</text>
      <path d={`M${w + 0.6},0V${h}M${w + 0.45},0H${w + 0.75}M${w + 0.45},${h}H${w + 0.75}`} />
      <text x={w + 1.1} y={h / 2} textAnchor="middle" transform={`rotate(90 ${w + 1.1} ${h / 2})`}>{metres(h)}</text>
      {ROOM.westWall.map(([from, to]) => (
        <text key={from} x={-0.3} y={(from + to) / 2} textAnchor="end" className="small">{cote(to - from)}</text>
      ))}
      {ROOM.pillars.map((p) => (
        <g key={p.y} className="small">
          <text x={-0.3} y={p.y + p.h / 2 + 0.1} textAnchor="end">{cote(p.h)}</text>
          <text x={p.w / 2} y={p.y - 0.12} textAnchor="middle">{cote(p.w)}</text>
        </g>
      ))}
      <g className="north" transform={`translate(${w + 1.4} 0.6)`}>
        <path d="M0,-0.35L0.2,0.35L0,0.2L-0.2,0.35Z" />
        <text y={-0.5} textAnchor="middle">N</text>
      </g>
      <g className="scale" transform={`translate(0 ${h + 1})`}>
        <path d="M0,0H5M0,-0.15V0.15M5,-0.15V0.15" />
        <text x={0} y={-0.25}>0</text>
        <text x={5.15} y={0.12}>5 m</text>
      </g>
    </g>
  );
}

export function MapView({ state, selected, onSelect }: Props) {
  const drone = state.drone;
  const rings = rangeRings(state.phones);
  const droneSelected = selected?.kind === "drone";
  const marker = drone?.track ?? drone?.zone; // la piste filtrée si elle existe, sinon la zone brute
  return (
    <svg className="map" viewBox={VIEWBOX} role="img" aria-label="Plan de salle : téléphones et drone">
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
      <Dimensions />
      <g className="rings">
        {rings.map((ring) => (
          <g key={ring.profile} className={`ring ${ring.fresh ? "" : "old"}`} data-ring={ring.profile}>
            <path d={annulusPath(ring.cx, ring.cy, ring.inner, ring.outer)} className="margin" fillRule="evenodd" />
            <circle cx={ring.cx} cy={ring.cy} r={ring.r} className="distance" />
          </g>
        ))}
      </g>
      {/* Zone brute (localiser_drone, un calcul par tick) en pâle sous la piste filtrée. */}
      {drone?.zone && (
        <circle cx={drone.zone.x_m} cy={drone.zone.y_m} r={drone.zone.radius_m} className={`zone ${drone.track ? "raw" : ""}`} />
      )}
      {drone?.track && (
        <circle cx={drone.track.x_m} cy={drone.track.y_m} r={drone.track.radius_m} className="zone" data-track="" />
      )}
      {drone?.truth && (
        <Clickable label="Drone simulé (position vraie)" selected={droneSelected} onSelect={() => onSelect({ kind: "drone" })} className="drone-marker ghost" x={drone.truth.x_m} y={drone.truth.y_m}>
          <g transform={`scale(${PX})`}><DroneIcon /></g>
        </Clickable>
      )}
      {/* Drone avant les téléphones : un téléphone survolé reste visible et cliquable. */}
      {marker && (
        <Clickable label="Drone (position calculée)" selected={droneSelected} onSelect={() => onSelect({ kind: "drone" })} className="drone-marker" x={marker.x_m} y={marker.y_m} data={{ "data-drone": drone?.track ? "tracked" : "located" }}>
          <circle r={0.75} className="selection" />
          <g transform={`scale(${PX})`}><DroneIcon /></g>
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
            {state_ === "on" && <circle r={0.48} className="pulse" />}
            <circle r={0.62} className="selection" />
            <g transform={`scale(${PX})`}><PhoneIcon /></g>
            <circle cx={0.42} cy={-0.42} r={0.14} className="listening-dot" />
          </Clickable>
        );
      })}
    </svg>
  );
}
