/** Iconographie du plan de salle (dessinée en px, 1 m = 40 px) : téléphone et drone quadricoptère. */

export const PX = 1 / 40; // échelle des icônes dans un SVG exprimé en mètres

export function PhoneIcon() {
  return (
    <g className="phone-icon">
      <circle r="19" className="halo" />
      <rect x="-8" y="-13" width="16" height="26" rx="3" className="body" />
      <rect x="-5.5" y="-9" width="11" height="15" className="screen" />
      <circle cy="9.5" r="1.4" className="button" />
    </g>
  );
}

export function DroneIcon() {
  return (
    <g className="drone-icon">
      <circle r="24" className="halo" />
      <g className="arms">
        <line x1="-11" y1="-11" x2="11" y2="11" />
        <line x1="11" y1="-11" x2="-11" y2="11" />
      </g>
      <g className="rotors">
        <circle cx="-11" cy="-11" r="6" />
        <circle cx="11" cy="-11" r="6" />
        <circle cx="-11" cy="11" r="6" />
        <circle cx="11" cy="11" r="6" />
      </g>
      <rect x="-5" y="-5" width="10" height="10" rx="2" className="core" />
    </g>
  );
}

/** Icône seule, pour la légende et le panneau. */
export function Glyph({ kind, size = 22 }: { kind: "phone" | "phone-detecting" | "drone" | "ghost"; size?: number }) {
  return (
    <svg viewBox="-26 -26 52 52" width={size} height={size} className={`glyph ${kind}`} aria-hidden="true">
      {kind.startsWith("phone") ? <PhoneIcon /> : <DroneIcon />}
    </svg>
  );
}
