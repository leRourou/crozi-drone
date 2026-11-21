import { describe, expect, it, vi } from "vitest";
import { buttonProps, isSelected } from "./selection";

const key = (k: string) => ({ key: k, preventDefault: vi.fn() });

describe("buttonProps", () => {
  it("makes a map marker a pressed-or-not button with an accessible name", () => {
    const props = buttonProps("Drone", true, () => {});
    expect({ ...props, onClick: undefined, onKeyDown: undefined }).toEqual({
      role: "button", tabIndex: 0, "aria-label": "Drone", "aria-pressed": true, onClick: undefined, onKeyDown: undefined,
    });
  });

  it("selects on click, Enter and Space, without scrolling the page", () => {
    const onSelect = vi.fn();
    const props = buttonProps("Drone", false, onSelect);
    props.onClick();
    const [enter, space, tab] = [key("Enter"), key(" "), key("Tab")];
    [enter, space, tab].forEach((e) => props.onKeyDown(e));
    expect(onSelect).toHaveBeenCalledTimes(3);
    expect([enter, space, tab].map((e) => e.preventDefault.mock.calls.length)).toEqual([1, 1, 0]);
  });
});

describe("isSelected", () => {
  it("matches the drone, or the same phone", () => {
    const noe = { kind: "phone", profile: "noe" } as const;
    expect(isSelected({ kind: "drone" }, { kind: "drone" })).toBe(true);
    expect(isSelected(noe, { kind: "phone", profile: "noe" })).toBe(true);
    expect(isSelected(noe, { kind: "phone", profile: "x" })).toBe(false);
    expect(isSelected(noe, { kind: "drone" })).toBe(false);
    expect(isSelected(null, { kind: "drone" })).toBe(false);
  });
});
