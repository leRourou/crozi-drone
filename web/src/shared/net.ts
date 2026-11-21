/** Réseau commun aux pages (téléphone, état) : URL WebSocket même origine et délai de reconnexion. */

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;

/** Délai avant une reconnexion, après `failures` échecs consécutifs : 1, 2, 4… plafonné à 30 s. */
export function reconnectDelayMs(failures: number): number {
  return Math.min(RECONNECT_BASE_MS * 2 ** failures, RECONNECT_MAX_MS);
}

/** URL WebSocket sur la même origine que la page (wss derrière HTTPS, ws en local). */
export function socketUrl(path: string, loc: Pick<Location, "protocol" | "host"> = location): string {
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${loc.host}${path}`;
}
