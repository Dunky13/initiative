import { describe, expect, it } from "vitest";

import { parseDuration } from "./ClockWidget";

describe("parseDuration", () => {
  it.each([
    ["25", 1500],
    [" 5 ", 300],
    ["5:30", 330],
    ["0:45", 45],
    ["1:05:00", 3900],
    ["24:00:00", 86400],
  ])("reads %s as %i seconds", (text, seconds) => {
    expect(parseDuration(text)).toBe(seconds);
  });

  it.each(["", "soon", "5:", "1:2:3:4", "-5", "2.5", "0", "0:00", "24:00:01"])(
    "takes %j as no length",
    (text) => {
      expect(parseDuration(text)).toBeNull();
    }
  );
});
