/** Shared by the AI fact pack and the page (TEST, Moose 2026-11-27). */
/** Most likely legs first (ties keep slip order). "Least likely" = every leg under 50% plus, always, the weakest leg;
 *  with a single leg, it is the one group its probability puts it in. Decided by the model, never by AI. */
export function likelihoodGroups(ps: number[]): { order: number[]; least: Set<number> } {
  const order = ps.map((p, i) => ({ p, i })).sort((a, b) => b.p - a.p || a.i - b.i).map((x) => x.i);
  const least = new Set(order.filter((i) => ps[i] < 0.5));
  if (ps.length > 1) least.add(order[order.length - 1]);
  return { order, least };
}
