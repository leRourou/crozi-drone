import type { LogLevel } from "./streamer";

export const MAX_LOG_LINES = 200;

export interface LogLine {
  id: number;
  time: string;
  text: string;
  level: LogLevel;
}

export function clock(date: Date): string {
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

/** Ajoute une ligne horodatée et ne garde que les MAX_LOG_LINES plus récentes. */
export function appendLog(lines: readonly LogLine[], line: LogLine, max = MAX_LOG_LINES): LogLine[] {
  return [...lines, line].slice(-max);
}
