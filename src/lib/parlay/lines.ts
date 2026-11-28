/**
 * Pure helpers shared by the server and the Parlay Builder cards (TEST, Moose 2026-11-27).
 *   - game lines: the engine's own normal approximation (modeling/modelroom/common/oddsmath.py over_probs /
 *     cover_probs / sigma_from_range), so a spread or total at any line uses exactly the engine's method
 *   - props: P(stat >= k) from the model's calibrated grid, and the last-10 record against an exact line
 */
import { phi } from "./joint";
import type { Last10 } from "./types";

export const Z80 = 1.2815515655446004;

export function sigmaFromRange(r: [number, number] | null | undefined): number | null {
  if (!r || r[0] == null || r[1] == null) return null;
  const s = (r[1] - r[0]) / (2 * Z80);
  return s > 0 ? s : null;
}

/** X ~ Normal(mean, sd) rounded to integers: P(X > line), P(X = line), P(X < line) (oddsmath.over_probs). */
export function overProbs(mean: number, sd: number, line: number) {
  if (Math.abs(line - Math.round(line)) < 1e-9) {
    const k = Math.round(line);
    const over = 1 - phi((k + 0.5 - mean) / sd);
    const push = phi((k + 0.5 - mean) / sd) - phi((k - 0.5 - mean) / sd);
    return { over, push, under: Math.max(0, 1 - over - push) };
  }
  const k = Math.floor(line) + 1;
  const over = 1 - phi((k - 0.5 - mean) / sd);
  return { over, push: 0, under: Math.max(0, 1 - over) };
}

/** Home spread `homeLine` (negative = home favored): home covers when margin + line > 0 (oddsmath.cover_probs). */
export function coverProbs(margin: number, sd: number, homeLine: number) {
  const p = overProbs(margin, sd, -homeLine);
  return { home: p.over, push: p.push, away: p.under };
}

/** P(stat >= k) from the calibrated grid; linear between grid points (flagged); null outside the grid. */
export function gridAt(g: { k0: number; step: number; p: number[] } | null | undefined, k: number): { p: number; interpolated: boolean } | null {
  if (!g || !g.p.length) return null;
  const idx = (k - g.k0) / g.step;
  if (idx < 0 || idx > g.p.length - 1) return null;
  const i = Math.floor(idx);
  const f = idx - i;
  if (f < 1e-9) return { p: g.p[i], interpolated: false };
  return { p: g.p[i] + f * (g.p[i + 1] - g.p[i]), interpolated: true };
}

/** Over / under a posted line L from the grid: half-point lines can't push; whole-number lines push at exactly L. */
export function propLine(g: { k0: number; step: number; p: number[] } | null | undefined, line: number) {
  const whole = Math.abs(line - Math.round(line)) < 1e-9;
  const over = gridAt(g, whole ? Math.round(line) + 1 : Math.ceil(line));
  const atLeast = whole ? gridAt(g, Math.round(line)) : over;
  if (!over || !atLeast) return null;
  return { over: over.p, under: Math.max(0, 1 - atLeast.p), push: whole ? Math.max(0, atLeast.p - over.p) : 0, interpolated: over.interpolated || atLeast.interpolated };
}

const fmt1 = (x: number) => (Math.round(x * 10) / 10).toFixed(1);

/**
 * The player's last 10 played games (newest first, from the board's box scores) against this exact line.
 *   kind "line" (a posted line L): over wins above L, push at exactly L, loss below
 *   kind "atleast" (K+): win at K or more; under K: win below K (no pushes)
 * null when there is no game log for this stat (never invented).
 */
export function last10(values: (number | null)[] | undefined, line: number, side: 1 | -1, kind: "line" | "atleast", noun: string, label: string): Last10 | null {
  const v = (values ?? []).filter((x): x is number => typeof x === "number" && Number.isFinite(x)).slice(0, 10);
  if (!v.length) return null;
  const res = v.map((x) => {
    if (kind === "atleast") return (side > 0 ? x >= line : x < line) ? 1 : -1;
    if (x === line) return 0;
    return (side > 0 ? x > line : x < line) ? 1 : -1;
  });
  const hits = res.filter((r) => r === 1).length;
  const pushes = res.filter((r) => r === 0).length;
  const five = res.slice(0, 5);
  const avg = v.reduce((a, b) => a + b, 0) / v.length;
  const l5 = five.filter((r) => r === 1).length;
  const text = `${label}: hit in ${hits} of last ${v.length}${pushes ? ` (${pushes} push${pushes > 1 ? "es" : ""})` : ""}. Averaging ${fmt1(avg)} ${noun}. ${l5} of the last ${five.length} hit.`;
  return { games: v.length, hits, misses: v.length - hits - pushes, pushes, avg: Math.round(avg * 10) / 10, last5Hits: l5, last5Games: five.length, values: v, marks: res, text };
}
