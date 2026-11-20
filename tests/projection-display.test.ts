import { describe, expect, it } from "vitest";
import { formatProjection } from "@/lib/format";

describe("player projections are displayed as whole numbers", () => {
  it("rounds to the nearest whole number, halves up, never a decimal", () => {
    expect(formatProjection(20.84)).toBe("21");
    expect(formatProjection(24.3)).toBe("24");
    expect(formatProjection(24.5)).toBe("25");
    expect(formatProjection(0.4)).toBe("0");
    expect(formatProjection(-0.3)).toBe("0");
    expect(formatProjection(71.0)).toBe("71");
    for (const x of [0.05, 1.49, 9.99, 33.333, 112.7]) expect(formatProjection(x)).toMatch(/^-?\d+$/);
  });
});
