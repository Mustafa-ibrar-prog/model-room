/** P2: probabilities at an exact line, pushes, and the preferred outcome. SYNTHETIC ladders. */
import { describe, expect, it } from "vitest";
import { atLeast, CLOSE_BAND, ladderBars, preferredOutcome, probsAtLine, type Ladder } from "@/lib/propOutcome";

// Count stat: P(X >= k) for k = 2..8 (a threes-made-like ladder).
const threes: Ladder = { k0: 2, step: 1, p: [0.9, 0.75, 0.55, 0.4, 0.25, 0.12, 0.05] };
// Yardage on a 5-yard grid, k = 40..70.
const yards: Ladder = { k0: 40, step: 5, p: [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2] };

describe("probsAtLine", () => {
  it("half line on a count stat: exact, no push, no interpolation", () => {
    const r = probsAtLine(threes, "over_under", 4.5)!;
    expect(r.over).toBeCloseTo(0.4); // P(X >= 5), not the average of P(>=4) and P(>=5)
    expect(r.under).toBeCloseTo(0.6);
    expect(r.push).toBe(0);
  });

  it("whole line on a count stat: the push is P(X = L) and the three add up to 1", () => {
    const r = probsAtLine(threes, "over_under", 4)!;
    expect(r.over).toBeCloseTo(0.4); // P(X >= 5)
    expect(r.push).toBeCloseTo(0.15); // P(X >= 4) - P(X >= 5)
    expect(r.under).toBeCloseTo(0.45); // 1 - P(X >= 4)
    expect(r.over + r.push! + r.under).toBeCloseTo(1);
  });

  it("an N+ contract is Over N-0.5 and can't push; a 'greater than' contract pays above T", () => {
    const ge = probsAtLine(threes, "contract_ge", 5)!;
    expect(ge.line).toBe(4.5);
    expect(ge.over).toBeCloseTo(0.4);
    expect(ge.push).toBe(0);
    const gt = probsAtLine(threes, "contract_gt", 4)!;
    expect(gt.over).toBeCloseTo(0.4); // 5 or more
  });

  it("yardage: interpolated over the 5-yard grid; a whole-yard push is not estimated", () => {
    const half = probsAtLine(yards, "over_under", 52.5)!;
    expect(half.over).toBeCloseTo(0.55);
    expect(half.push).toBe(0);
    const whole = probsAtLine(yards, "over_under", 55)!;
    expect(whole.over).toBeCloseTo(0.5);
    expect(whole.push).toBeNull();
  });

  it("flags lines outside the simulated range", () => {
    expect(probsAtLine(threes, "over_under", 12.5)!.outsideRange).toBe(true);
    expect(atLeast(threes, 0, true).outside).toBe(true);
  });
});

describe("preferredOutcome", () => {
  it("follows the probability, not the average", () => {
    // Line 4.5: Over 40% / Under 60%; average 4.8 sits above the line (a long right tail).
    const p = preferredOutcome(probsAtLine(threes, "over_under", 4.5), { support: "ok", mean: 4.8 });
    expect(p).toMatchObject({ kind: "side", side: "under", againstAverage: true });
    if (p.kind === "side") expect(p.prob).toBeCloseTo(0.6);
  });

  it("is too close to call within the band, judged with pushes set aside", () => {
    const g: Ladder = { k0: 3, step: 1, p: [0.8, 0.6, 0.4, 0.2] }; // whole line 4: over 0.4, push 0.2, under 0.4
    const p = preferredOutcome(probsAtLine(g, "over_under", 4), { support: "ok" });
    expect(p.kind).toBe("close");
    const nearly: Ladder = { k0: 1, step: 1, p: [0.9, 0.5 + CLOSE_BAND / 2] };
    expect(preferredOutcome(probsAtLine(nearly, "contract_ge", 2), { support: "ok" }).kind).toBe("close");
  });

  it("shows nothing without a market line, with insufficient history, or outside the simulated range", () => {
    expect(preferredOutcome(null, { support: "ok" })).toEqual({ kind: "none", reason: "no_market_line" });
    expect(preferredOutcome(probsAtLine(threes, "over_under", 4.5), { support: "insufficient" })).toEqual({ kind: "none", reason: "insufficient_history" });
    expect(preferredOutcome(probsAtLine(threes, "over_under", 20.5), { support: "ok" })).toEqual({ kind: "none", reason: "outside_range" });
  });

  it("prefers Over when the over probability is clearly higher, and reports the push-free probability", () => {
    const g: Ladder = { k0: 3, step: 1, p: [0.95, 0.8, 0.7, 0.3] }; // whole line 4: over 0.7, push 0.1, under 0.2
    const p = preferredOutcome(probsAtLine(g, "over_under", 4), { support: "limited", mean: 4.6 });
    expect(p).toMatchObject({ kind: "side", side: "over", againstAverage: false });
    if (p.kind === "side") {
      expect(p.prob).toBeCloseTo(0.7);
      expect(p.noPushProb).toBeCloseTo(0.7 / 0.9);
    }
  });
});

describe("ladderBars", () => {
  it("turns the ladder into probability mass that sums to 1", () => {
    const bars = ladderBars(threes);
    expect(bars[0]).toMatchObject({ from: 0, to: 1 });
    expect(bars.reduce((s, b) => s + b.p, 0)).toBeCloseTo(1);
    expect(bars.find((b) => b.from === 4)!.p).toBeCloseTo(0.15);
  });
});
