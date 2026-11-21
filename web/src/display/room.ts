/**
 * Plan de la salle de démo, en mètres (repère du contrat des profils : origine au coin nord-ouest,
 * x vers l'est, y vers le sud). Relevé du plan fourni par l'équipe (1 m = 40 px, origine 80 ; 60).
 */

type Pt = readonly [number, number];

export const ROOM = {
  width_m: 10.4,
  height_m: 20.9,
  /** Contour intérieur des murs, avec les deux piliers en saillie sur le mur ouest. */
  outline: [
    [0, 0], [10.4, 0], [10.4, 20.9], [0, 20.9], [0, 12.79], [1.06, 12.79],
    [1.06, 11.86], [0, 11.86], [0, 9.66], [1.06, 9.66], [1.06, 8.73], [0, 8.73],
  ] as readonly Pt[],
  pillars: [
    { x: 0, y: 8.73, w: 1.06, h: 0.93 },
    { x: 0, y: 11.86, w: 1.06, h: 0.93 },
  ],
  /** Cotes du mur ouest entre les piliers : [début, fin] en y. */
  westWall: [
    [0, 8.73],
    [9.66, 11.86],
    [12.79, 20.9],
  ] as readonly Pt[],
} as const;

export const outlinePath = `M${ROOM.outline.map(([x, y]) => `${x},${y}`).join("L")}Z`;
