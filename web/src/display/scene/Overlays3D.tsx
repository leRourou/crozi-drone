/**
 * Marqueurs cliquables de la vue 3D : de simples <div> dans l'arbre React de la page, posés par-dessus le canvas.
 * `Overlays` les dessine (accessibles au clavier, mêmes classes / data-* que le plan 2D, lus par les tests e2e) ;
 * `OverlayProjector`, dans le canvas, les place à chaque image à la projection de leur position 3D.
 * (drei <Html> crée une racine React par marqueur et casse au démontage du canvas : on s'en passe.)
 */
import { useFrame } from "@react-three/fiber";
import type { RefObject } from "react";
import { Glyph } from "../icons";
import { type MapMarker, projectToScreen } from "../scene3d";
import { buttonProps, isSelected, type Selection } from "../selection";

export type OverlayElements = RefObject<Map<string, HTMLDivElement>>;

const GLYPH_SIZE: Record<MapMarker["glyph"], number> = { phone: 28, drone: 30, ghost: 26 };

interface OverlaysProps {
  markers: readonly MapMarker[];
  elements: OverlayElements;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}

export function Overlays({ markers, elements, selected, onSelect }: OverlaysProps) {
  const register = (key: string) => (el: HTMLDivElement | null) => {
    if (el) elements.current.set(key, el);
    else elements.current.delete(key);
  };
  return (
    <div className="overlays">
      {markers.map((m) => {
        const pressed = isSelected(selected, m.select);
        return (
          <div
            key={m.key}
            ref={register(m.key)}
            className={`marker3d ${m.className} ${pressed ? "selected" : ""}`}
            {...buttonProps(m.label, pressed, () => onSelect(m.select))}
            {...m.data}
          >
            <Glyph kind={m.glyph} size={GLYPH_SIZE[m.glyph]} />
            {m.glyph === "phone" && <span className="listening-dot" />}
          </div>
        );
      })}
    </div>
  );
}

export function OverlayProjector({ markers, elements }: { markers: readonly MapMarker[]; elements: OverlayElements }) {
  useFrame(({ camera, size }) => {
    for (const m of markers) {
      const el = elements.current.get(m.key);
      if (!el) continue;
      const { x, y, visible } = projectToScreen(m.position, camera, size);
      el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
      el.style.visibility = visible ? "visible" : "hidden";
    }
  });
  return null;
}
