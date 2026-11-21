/** Objet sélectionné sur le plan (2D ou 3D) et dans le panneau. */
export type Selection = { kind: "phone"; profile: string } | { kind: "drone" } | null;

/** Marqueur du plan (SVG ou surcouche HTML de la 3D) rendu cliquable et activable au clavier. */
export function buttonProps(label: string, selected: boolean, onSelect: () => void) {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    "aria-pressed": selected,
    onClick: onSelect,
    onKeyDown: (e: { key: string; preventDefault: () => void }) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault(); // Espace ferait défiler la page
      onSelect();
    },
  } as const;
}

/** `target` (un objet du plan) est-il l'objet sélectionné ? */
export function isSelected(selected: Selection, target: Exclude<Selection, null>): boolean {
  if (selected?.kind !== target.kind) return false;
  return target.kind === "drone" || (selected.kind === "phone" && selected.profile === target.profile);
}
