import { describe, expect, it } from "vitest";
import { appendLog, clock, type LogLine } from "./logbuffer";

const line = (id: number): LogLine => ({ id, time: "t", text: `l${id}`, level: "info" });

describe("appendLog", () => {
  it("keeps only the most recent lines, in order", () => {
    let lines: LogLine[] = [];
    for (let i = 0; i < 5; i += 1) lines = appendLog(lines, line(i), 3);
    expect(lines.map((l) => l.id)).toEqual([2, 3, 4]);
  });

  it("keeps everything below the limit", () => {
    expect(appendLog([line(0)], line(1), 2).map((l) => l.id)).toEqual([0, 1]);
  });
});

describe("clock", () => {
  it("formats local time with milliseconds", () => {
    expect(clock(new Date(2026, 10, 21, 9, 5, 7, 42))).toBe("09:05:07.042");
  });
});
