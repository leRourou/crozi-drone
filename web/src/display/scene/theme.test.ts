import { describe, expect, it } from "vitest";
import { readSceneColors } from "./theme";

describe("readSceneColors", () => {
  it("takes the 3D colours from the page palette (CSS variables), trimmed", () => {
    const css: Record<string, string> = {
      "--bg": " #151a12", "--floor": "#232b1f", "--grid": "#34402e", "--wall": "#c9d1a8",
      "--phone": "#f2c14e", "--phone-detecting": "#ff4d4d", "--drone": "#4aa3ff ",
    };
    expect(readSceneColors({ getPropertyValue: (name: string) => css[name] })).toEqual({
      bg: "#151a12", floor: "#232b1f", grid: "#34402e", wall: "#c9d1a8",
      phone: "#f2c14e", phoneDetecting: "#ff4d4d", drone: "#4aa3ff",
    });
  });
});
