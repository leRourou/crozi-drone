/** Couleurs de la scène 3D, lues une fois dans les variables CSS de styles.css (une seule palette). */
export interface SceneColors {
  bg: string;
  floor: string;
  grid: string;
  wall: string;
  phone: string;
  phoneDetecting: string;
  drone: string;
}

const VARS: Record<keyof SceneColors, string> = {
  bg: "--bg",
  floor: "--floor",
  grid: "--grid",
  wall: "--wall",
  phone: "--phone",
  phoneDetecting: "--phone-detecting",
  drone: "--drone",
};

/** `style` : getComputedStyle(main.display). */
export function readSceneColors(style: Pick<CSSStyleDeclaration, "getPropertyValue">): SceneColors {
  const entries = Object.entries(VARS).map(([key, name]) => [key, style.getPropertyValue(name).trim()]);
  return Object.fromEntries(entries) as SceneColors;
}
