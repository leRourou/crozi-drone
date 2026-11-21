/** Symbologie du plan (Vigie C2, inspirée d'APP-6), dessinée en px : 1 m = 40 px. */

export const PX = 1 / 40; // échelle des symboles dans un SVG exprimé en mètres

/** Capteur (téléphone) : rectangle du domaine terrestre, lettre T. */
export function SensorIcon() {
  return (
    <g className="sensor">
      <rect x="-10" y="-7" width="20" height="14" className="frame" />
      <text className="letter">T</text>
    </g>
  );
}

/** Piste : demi-losange ouvert vers le bas (domaine aérien). */
export function TrackIcon() {
  return (
    <g className="track">
      <path d="M-11 8V-1L0-10L11-1V8" className="frame" />
    </g>
  );
}

/** Position vraie du drone simulé : croix violette. */
export function TruthIcon() {
  return (
    <g className="truth">
      <path d="M-6 0H6M0-6V6" />
    </g>
  );
}

/** Réticule de sélection (quatre coins), autour d'une boîte de demi-largeur w et demi-hauteur h. */
export function Reticle({ w, h }: { w: number; h: number }) {
  const c = 7;
  return (
    <path
      className="reticle"
      d={`M${-w},${-h + c}V${-h}H${-w + c}M${w - c},${-h}H${w}V${-h + c}M${w},${h - c}V${h}H${w - c}M${-w + c},${h}H${-w}V${h - c}`}
    />
  );
}
