/**
 * Model Room probabilities at a market's exact line, and the preferred outcome they imply (P2).
 *
 * Everything here reads the board's published, calibrated ladder: grid.p[i] = P(stat >= k0 + i·step) after the model's
 * calibration, the same numbers every other probability on the site comes from. Nothing is re-estimated: no new
 * distribution, no smoothing, no confidence labels.
 *
 *   Count stats (points, receptions, attempts…: grid step 1). Exact at any line:
 *     half line L       Over = P(X ≥ ⌈L⌉), Push = 0, Under = 1 − Over
 *     whole line L      Over = P(X ≥ L+1), Push = P(X ≥ L) − P(X ≥ L+1), Under = 1 − P(X ≥ L)
 *   Yardage (grid step 5; the simulation draws yards as continuous amounts): Over is interpolated between grid points;
 *   a push at a whole-yard line is not estimated (the model has no mass on exact yard values), so Push is null.
 *
 * Exchange contracts are binary: "N+" (op ≥) pays Yes at N or more, which is Over N − 0.5; "greater than T" (op >) pays
 * Yes above T. They can't push. A sportsbook over/under at a whole number can.
 *
 * Preferred outcome: the side with the higher model probability at that line, judged with pushes set aside; "too close
 * to call" when that is within CLOSE_BAND of even. Never from the projected average: the average can sit above the line
 * while most of the distribution sits below it (a few big games pull the average up).
 */

export interface Ladder {
  k0: number;
  step: number;
  p: number[];
}

/** Within this distance of 50/50 (pushes set aside), no side is preferred. */
export const CLOSE_BAND = 0.03;

export type LineKind = "over_under" | "contract_ge" | "contract_gt";

export interface LineProbs {
  over: number;
  under: number;
  /** null: not estimated (yardage at a whole-yard line); 0: impossible at this line or contract. */
  push: number | null;
  /** The line lies outside the simulated range (beyond the 1st–99th percentile grid): the end value is used. */
  outsideRange: boolean;
  /** Over / Under as in a sportsbook line ("Over 24.5"). */
  line: number;
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** P(X ≥ k) from the ladder. Count stats: exact at whole k (⌈k⌉ for fractional k). Yardage: linear between points. */
export function atLeast(g: Ladder, k: number, count: boolean): { p: number; outside: boolean } {
  const n = g.p.length;
  if (!n) return { p: NaN, outside: true };
  const kk = count ? Math.ceil(k - 1e-9) : k;
  const x = (kk - g.k0) / g.step;
  if (x < 0) return { p: g.p[0], outside: true };
  if (x > n - 1) return { p: g.p[n - 1], outside: true };
  if (count || g.step === 1) return { p: g.p[Math.round(x)], outside: false };
  const i = Math.floor(x);
  const f = x - i;
  return { p: i + 1 < n ? g.p[i] * (1 - f) + g.p[i + 1] * f : g.p[i], outside: false };
}

/** Grid step 1 = a count stat (the board publishes yardage on a 5-yard grid). */
export const isCountLadder = (g: Ladder) => g.step === 1;

/** Over / Push / Under at an exact market line or contract. */
export function probsAtLine(g: Ladder, kind: LineKind, threshold: number): LineProbs | null {
  if (!g.p.length || !Number.isFinite(threshold)) return null;
  const count = isCountLadder(g);
  if (kind === "contract_ge") {
    const a = atLeast(g, threshold, count);
    return { over: a.p, under: 1 - a.p, push: 0, outsideRange: a.outside, line: threshold - 0.5 };
  }
  if (kind === "contract_gt") {
    // Yes above T: for a count stat, T+1 or more when T is whole, ⌈T⌉ or more otherwise.
    const k = count ? Math.floor(threshold) + 1 : threshold;
    const a = atLeast(g, k, count);
    return { over: a.p, under: 1 - a.p, push: 0, outsideRange: a.outside, line: threshold };
  }
  const L = threshold;
  if (count) {
    if (Number.isInteger(L)) {
      const ge = atLeast(g, L, true);
      const gt = atLeast(g, L + 1, true);
      return { over: gt.p, push: clamp01(ge.p - gt.p), under: 1 - ge.p, outsideRange: ge.outside || gt.outside, line: L };
    }
    const a = atLeast(g, Math.ceil(L), true);
    return { over: a.p, push: 0, under: 1 - a.p, outsideRange: a.outside, line: L };
  }
  const a = atLeast(g, L, false);
  return { over: a.p, push: Number.isInteger(L) ? null : 0, under: 1 - a.p, outsideRange: a.outside, line: L };
}

export type Preferred =
  | { kind: "side"; side: "over" | "under"; prob: number; noPushProb: number; againstAverage: boolean }
  | { kind: "close"; noPushOver: number }
  | { kind: "none"; reason: "no_market_line" | "insufficient_history" | "outside_range" };

/**
 * Preferred outcome at a market line. `mean` is only used to say when the preference runs against the average (so the
 * card can explain it); it never decides the side.
 */
export function preferredOutcome(pr: LineProbs | null, opts: { support: "ok" | "limited" | "insufficient"; mean?: number | null }): Preferred {
  if (!pr) return { kind: "none", reason: "no_market_line" };
  if (opts.support === "insufficient") return { kind: "none", reason: "insufficient_history" };
  if (pr.outsideRange) return { kind: "none", reason: "outside_range" };
  const decided = pr.over + pr.under;
  if (!(decided > 0)) return { kind: "none", reason: "outside_range" };
  const o = pr.over / decided;
  if (Math.abs(o - 0.5) < CLOSE_BAND) return { kind: "close", noPushOver: o };
  const side = o > 0.5 ? "over" : "under";
  const meanSide = opts.mean == null || opts.mean === pr.line ? null : opts.mean > pr.line ? "over" : "under";
  return { kind: "side", side, prob: side === "over" ? pr.over : pr.under, noPushProb: side === "over" ? o : 1 - o, againstAverage: meanSide !== null && meanSide !== side };
}

/** "24.5" / "25" for display. */
export const lineText = (x: number) => (Number.isInteger(x) ? x.toFixed(0) : x.toFixed(1));

/**
 * Probability mass per outcome from the ladder, for the distribution chart: count stats one bar per value, yardage one
 * bar per 5-yard bin. The first bar holds everything below the grid's start, the last everything from its end up.
 */
export function ladderBars(g: Ladder): { from: number; to: number | null; p: number }[] {
  const n = g.p.length;
  if (!n) return [];
  const out: { from: number; to: number | null; p: number }[] = [];
  if (g.k0 > 0) out.push({ from: 0, to: g.k0 - (isCountLadder(g) ? 1 : 0), p: clamp01(1 - g.p[0]) });
  for (let i = 0; i < n; i++) {
    const next = i + 1 < n ? g.p[i + 1] : 0;
    out.push({ from: g.k0 + i * g.step, to: i + 1 < n ? g.k0 + (i + 1) * g.step - (isCountLadder(g) ? 1 : 0) : null, p: clamp01(g.p[i] - next) });
  }
  return out;
}
