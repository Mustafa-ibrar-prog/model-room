import { describe, expect, it } from "vitest";
import fx from "./fixtures/parlay-joint.json";
import { americanToDecimal, bvnu, decimalToAmerican, fairAmerican, frechet, invPhi, joint, nearestCorr, phi } from "@/lib/parlay/joint";

/** Reference values come from Python (statistics.NormalDist, scipy multivariate_normal): tests/fixtures/parlay-joint.json. */
describe("parlay joint engine: normal functions", () => {
  it("phi matches the reference to 1e-12", () => {
    for (const [x, ref] of fx.phi) expect(Math.abs(phi(x) - ref)).toBeLessThan(1e-12);
  });
  it("invPhi matches the reference and round-trips", () => {
    for (const [p, ref] of fx.inv) expect(Math.abs(invPhi(p) - ref)).toBeLessThan(1e-9);
    for (const p of [0.001, 0.2, 0.5, 0.93]) expect(Math.abs(phi(invPhi(p)) - p)).toBeLessThan(1e-12);
  });
  it("bivariate upper orthant matches scipy to 1e-9", () => {
    for (const [h, k, r, ref] of fx.bvnu) expect(Math.abs(bvnu(h, k, r) - ref)).toBeLessThan(1e-9);
  });
  it("bivariate edge cases: independence, infinities", () => {
    expect(bvnu(0, 0, 0)).toBeCloseTo(0.25, 12);
    expect(bvnu(-Infinity, 0.5, 0.4)).toBeCloseTo(phi(-0.5), 12);
    expect(bvnu(Infinity, 0, 0.4)).toBe(0);
    expect(bvnu(0, 0, 0.5)).toBeCloseTo(0.25 + Math.asin(0.5) / (2 * Math.PI), 10);
  });
});

describe("parlay joint engine: joint probability", () => {
  const R = fx.R;
  it("three legs on three variables agree with scipy within 4 standard errors", () => {
    const legs = fx.legs.map((l) => ({ variable: l.var, side: l.side as 1 | -1, p: l.p }));
    const r = joint(legs, R);
    expect(r.method).toMatch(/^genz_/);
    expect(Math.abs(r.p - fx.ref3)).toBeLessThan(4 * r.se + 1e-4);
  });
  it("is deterministic (seeded)", () => {
    const legs = fx.legs.map((l) => ({ variable: l.var, side: l.side as 1 | -1, p: l.p }));
    expect(joint(legs, R).p).toBe(joint(legs, R).p);
  });
  it("independent legs multiply", () => {
    const I = [[1, 0], [0, 1]];
    expect(joint([{ variable: 0, side: 1, p: 0.6 }, { variable: 1, side: 1, p: 0.5 }], I).p).toBeCloseTo(0.3, 12);
  });
  it("positive correlation raises the joint; negative lowers it", () => {
    const legs = [{ variable: 0, side: 1 as const, p: 0.5 }, { variable: 1, side: 1 as const, p: 0.5 }];
    const up = joint(legs, [[1, 0.4], [0.4, 1]]).p;
    const down = joint(legs, [[1, -0.4], [-0.4, 1]]).p;
    expect(up).toBeGreaterThan(0.25);
    expect(down).toBeLessThan(0.25);
    // flipping one side flips the effect
    expect(joint([legs[0], { ...legs[1], side: -1 }], [[1, 0.4], [0.4, 1]]).p).toBeCloseTo(down, 12);
  });
  it("legs on the same variable: nested lines take the stricter, opposite lines make an interval, impossible is 0", () => {
    const I = [[1]];
    expect(joint([{ variable: 0, side: 1, p: 0.6 }, { variable: 0, side: 1, p: 0.3 }], I).p).toBeCloseTo(0.3, 12);
    expect(joint([{ variable: 0, side: 1, p: 0.6 }, { variable: 0, side: -1, p: 0.6 }], I).p).toBeCloseTo(0.2, 12);
    expect(joint([{ variable: 0, side: 1, p: 0.3 }, { variable: 0, side: -1, p: 0.3 }], I).p).toBe(0);
  });
  it("a certain leg drops out; an impossible leg makes the parlay 0", () => {
    expect(joint([{ variable: 0, side: 1, p: 1 }, { variable: 1, side: 1, p: 0.4 }], [[1, 0], [0, 1]]).p).toBeCloseTo(0.4, 12);
    expect(joint([{ variable: 0, side: 1, p: 0 }, { variable: 1, side: 1, p: 0.4 }], [[1, 0], [0, 1]]).p).toBe(0);
  });
  it("repairs an invalid correlation matrix", () => {
    const bad = [[1, 0.9, 0.9], [0.9, 1, -0.9], [0.9, -0.9, 1]];
    const fixed = nearestCorr(bad);
    for (let i = 0; i < 3; i++) expect(fixed[i][i]).toBeCloseTo(1, 9);
    const r = joint([0, 1, 2].map((v) => ({ variable: v, side: 1 as const, p: 0.5 })), bad);
    expect(r.p).toBeGreaterThanOrEqual(0);
    expect(r.p).toBeLessThanOrEqual(0.5);
  });
});

describe("parlay odds helpers", () => {
  it("Fréchet bounds", () => {
    const [lo, hi] = frechet([0.6, 0.7]);
    expect(lo).toBeCloseTo(0.3, 12);
    expect(hi).toBe(0.6);
    expect(frechet([0.2, 0.3, 0.4])).toEqual([0, 0.2]);
  });
  it("fair odds and conversions", () => {
    expect(fairAmerican(0.5)).toBe(-100);
    expect(fairAmerican(0.25)).toBe(300);
    expect(fairAmerican(0.8)).toBe(-400);
    expect(fairAmerican(0)).toBeNull();
    expect(americanToDecimal(150)).toBeCloseTo(2.5, 12);
    expect(americanToDecimal(-200)).toBeCloseTo(1.5, 12);
    expect(decimalToAmerican(2.5)).toBe(150);
    expect(decimalToAmerican(1.5)).toBe(-200);
  });
});
