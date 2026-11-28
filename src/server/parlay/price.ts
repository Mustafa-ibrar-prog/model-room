import "server-only";
import { americanToDecimal, decimalToAmerican, fairAmerican, frechet, joint, type JointLeg } from "@/lib/parlay/joint";
import type { LegResult, ParlayPrice } from "@/lib/parlay/types";
import type { Catalog, CatalogLeg } from "./legs";
import { relate, variableKey, type Table } from "./correlations";

/**
 * Prices a parlay from leg ids (TEST, Moose 2026-11-27). Every number comes from stored model output and the historical
 * correlation table; the request carries ids only.
 *
 *   point     Gaussian-copula joint probability with the measured coefficients (exact for two variables, Genz otherwise)
 *   range     the same with every coefficient at the end of its 95% interval that lowers / raises the joint, plus
 *             integration error; a game whose legs have no measured coefficient gets Fréchet bounds and no point
 *   compare   the legs multiplied as if unrelated
 */
export const MAX_LEGS = 10;
const STALE_HOURS = 30;

export function priceParlay(ids: string[], catalogs: Catalog[], table: Table | null, now = new Date()): ParlayPrice {
  const empty: ParlayPrice = { ok: false, legs: [], rejected: [], p: null, range: null, independent: null, correlationEffect: null,
    fairAmerican: null, fairDecimal: null, bookIfSeparate: null, method: "", warnings: [], pairs: [], dataAsOf: [] };
  const unique = [...new Set(ids)].slice(0, MAX_LEGS + 1);
  if (unique.length > MAX_LEGS) return { ...empty, error: `Up to ${MAX_LEGS} legs.` };
  const found: { leg: CatalogLeg; cat: Catalog }[] = [];
  const rejected: { id: string; reason: string }[] = [];
  for (const id of unique) {
    let hit: { leg: CatalogLeg; cat: Catalog } | null = null;
    for (const c of catalogs) {
      const l = c.legs.get(id) ?? c.resolve?.(id) ?? null;
      if (l) { hit = { leg: l, cat: c }; break; }
    }
    if (!hit) rejected.push({ id, reason: "This leg is no longer available: the game started, the line moved or the data was refreshed." });
    else found.push(hit);
  }
  const dataAsOf = catalogs.flatMap((c) => c.asOf);
  if (!found.length) return { ...empty, rejected, dataAsOf, error: rejected.length ? "None of these legs can be priced now." : "Add at least one leg." };
  if (!table) return { ...empty, rejected, dataAsOf, error: "The correlation table isn't available, so this parlay can't be priced." };

  // Variables
  const vIndex = new Map<string, number>();
  const vars: CatalogLeg["variable"][] = [];
  for (const { leg } of found) {
    const k = variableKey(leg.variable);
    if (!vIndex.has(k)) {
      vIndex.set(k, vars.length);
      vars.push(leg.variable);
    }
  }
  const n = vars.length;
  const R = eye(n), Rlo = eye(n), Rhi = eye(n);
  const legsJ: JointLeg[] = found.map(({ leg }) => ({ variable: vIndex.get(variableKey(leg.variable))!, side: leg.side, p: leg.option.p }));
  // orientation per variable: +1 / -1 if every leg on it points the same way, 0 if they bracket it
  const orient = new Array<number>(n).fill(NaN);
  for (const l of legsJ) orient[l.variable] = Number.isNaN(orient[l.variable]) ? l.side : orient[l.variable] === l.side ? l.side : 0;
  const firstLeg = new Array<number>(n).fill(-1);
  legsJ.forEach((l, i) => {
    if (firstLeg[l.variable] < 0) firstLeg[l.variable] = i;
  });
  const missing: [number, number][] = [];
  const pairs: ParlayPrice["pairs"] = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const rel = relate(table, vars[i], vars[j]);
      if (!rel) {
        missing.push([i, j]);
        continue;
      }
      R[i][j] = R[j][i] = rel.r;
      const s = orient[i] * orient[j];
      const [down, up] = s > 0 ? [rel.lo, rel.hi] : s < 0 ? [rel.hi, rel.lo] : [rel.r, rel.r];
      Rlo[i][j] = Rlo[j][i] = down;
      Rhi[i][j] = Rhi[j][i] = up;
      if (vars[i].gameId === vars[j].gameId && vars[i].league === vars[j].league) pairs.push({ a: firstLeg[i], b: firstLeg[j], r: rel.r, relation: rel.relation });
    }
  }

  const ps = legsJ.map((l) => l.p);
  const independent = ps.reduce((a, b) => a * b, 1);
  let p: number | null = null;
  let range: [number, number];
  let method: string;
  const warnings: ParlayPrice["warnings"] = [];
  if (!missing.length) {
    const mid = joint(legsJ, R);
    const lo = joint(legsJ, Rlo);
    const hi = joint(legsJ, Rhi);
    p = mid.p;
    const err = 2 * Math.max(mid.se, lo.se, hi.se);
    range = [Math.max(0, Math.min(mid.p, lo.p, hi.p) - err), Math.min(1, Math.max(mid.p, lo.p, hi.p) + err)];
    method = mid.method === "exact" ? "Exact bivariate normal on the measured correlations" : "Genz integration on the measured correlations (20,000 samples)";
  } else {
    // Bounds per game block: blocks with full coefficients get their range, the others Fréchet bounds; games multiply.
    const blocks = new Map<string, number[]>();
    legsJ.forEach((l, i) => {
      const v = vars[l.variable];
      const g = `${v.league}~${v.gameId}`;
      (blocks.get(g) ?? blocks.set(g, []).get(g)!).push(i);
    });
    let lo = 1, hi = 1;
    for (const idx of blocks.values()) {
      const bl = idx.map((i) => legsJ[i]);
      const bv = new Set(bl.map((l) => l.variable));
      const blockMissing = missing.some(([a, b]) => bv.has(a) && bv.has(b));
      if (blockMissing) {
        const [a, b] = frechet(bl.map((l) => l.p));
        lo *= a;
        hi *= b;
      } else {
        const x = [joint(bl, R), joint(bl, Rlo), joint(bl, Rhi)];
        lo *= Math.max(0, Math.min(...x.map((r) => r.p)) - 2 * Math.max(...x.map((r) => r.se)));
        hi *= Math.min(1, Math.max(...x.map((r) => r.p)) + 2 * Math.max(...x.map((r) => r.se)));
      }
    }
    range = [lo, hi];
    method = "Bounds only: some legs in the same game have no measured correlation, so no single number is given";
    const names = missing.slice(0, 3).map(([a, b]) => `${varName(found, vIndex, a)} and ${varName(found, vIndex, b)}`);
    warnings.push({ level: "caution", text: `Not enough history to measure how ${names.join("; ")} move together. Showing the range that holds whatever the link.` });
  }

  // Legs, prices, warnings
  const legs: LegResult[] = found.map(({ leg, cat }) => ({ ...leg.option, gameLabel: cat.gameLabel.get(leg.option.gameId) ?? leg.option.gameId, warnings: legWarnings(leg) }));
  const priced = legs.filter((l) => l.price);
  const bookIfSeparate = priced.length === legs.length
    ? (() => { const d = legs.reduce((a, l) => a * americanToDecimal(l.price!.american), 1); return { decimal: round(d, 3), american: decimalToAmerican(d), legsPriced: legs.length }; })()
    : null;
  warnings.push(...parlayWarnings(found, legsJ, pairs, vars, p, independent, legs, now));
  for (const r of rejected) warnings.push({ level: "caution", text: r.reason });

  return {
    ok: true, legs, rejected, p: p === null ? null : round(p, 4), range: [round(range[0], 4), round(range[1], 4)],
    independent: round(independent, 4), correlationEffect: p === null || independent <= 0 ? null : round(p / independent, 3),
    fairAmerican: p === null ? null : fairAmerican(p), fairDecimal: p === null || p <= 0 ? null : round(1 / p, 2),
    bookIfSeparate, method, warnings, pairs, dataAsOf,
  };
}

function eye(n: number): number[][] {
  return Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)));
}
const round = (x: number, d: number) => Math.round(x * 10 ** d) / 10 ** d;

function varName(found: { leg: CatalogLeg }[], vIndex: Map<string, number>, i: number) {
  const f = found.find(({ leg }) => vIndex.get(variableKey(leg.variable)) === i)!;
  const o = f.leg.option;
  return o.kind === "prop" ? `${o.playerName} ${o.group.toLowerCase()}` : o.kind === "total" ? "the game total" : "the game result";
}

function legWarnings(l: CatalogLeg): string[] {
  const o = l.option;
  const w: string[] = [];
  if (o.injury && !/^available$/i.test(o.injury)) w.push(`Listed ${o.injury.toLowerCase()}.`);
  if (o.support === "limited") w.push("Limited history for this player and stat.");
  if (o.push) w.push(`Can push (${(o.push * 100).toFixed(1)}%): a push is not a win here.`);
  if (!o.price) w.push(`${o.noPrice ?? "No sportsbook price available"}.`);
  if (o.interpolated) w.push("Probability read between two points of the model's distribution.");
  return w;
}

function parlayWarnings(found: { leg: CatalogLeg; cat: Catalog }[], legsJ: JointLeg[], pairs: ParlayPrice["pairs"], vars: CatalogLeg["variable"][],
  p: number | null, independent: number, legs: LegResult[], now: Date): ParlayPrice["warnings"] {
  const w: ParlayPrice["warnings"] = [];
  // same variable twice
  const byVar = new Map<number, number[]>();
  legsJ.forEach((l, i) => (byVar.get(l.variable) ?? byVar.set(l.variable, []).get(l.variable)!).push(i));
  for (const idx of byVar.values()) {
    if (idx.length < 2) continue;
    const sides = new Set(idx.map((i) => legsJ[i].side));
    const names = idx.map((i) => legs[i].label).join(" and ");
    if (p === 0) w.push({ level: "risk", text: `${names} can't both win.` });
    else if (sides.size === 1) w.push({ level: "info", text: `${names} overlap: the stricter one decides both.` });
    else w.push({ level: "caution", text: `${names} need the result to land in a narrow window.` });
  }
  // strong links inside a game (oriented by the legs' sides)
  for (const pr of pairs) {
    if (pr.relation === "same stat" || pr.relation === "same line") continue;
    const la = pr.a;
    const lb = pr.b;
    const eff = pr.r * legsJ[la].side * legsJ[lb].side;
    if (Math.abs(eff) < 0.1) continue;
    w.push(eff > 0
      ? { level: "info", text: `${legs[la].label} and ${legs[lb].label} tend to win together (${pr.relation}).` }
      : { level: "caution", text: `${legs[la].label} and ${legs[lb].label} work against each other (${pr.relation}).` });
  }
  if (p !== null && independent > 0) {
    const eff = p / independent;
    if (eff >= 1.1) w.push({ level: "info", text: `Correlation makes this ${Math.round((eff - 1) * 100)}% more likely than the legs multiplied.` });
    if (eff <= 0.9) w.push({ level: "caution", text: `Correlation makes this ${Math.round((1 - eff) * 100)}% less likely than the legs multiplied.` });
  }
  if (p !== null && p < 0.05) w.push({ level: "risk", text: "Long shot: under a 5% chance on the model." });
  if (legs.length >= 6) w.push({ level: "caution", text: "Every extra leg multiplies the risk." });
  const games = new Set(vars.map((v) => `${v.league}~${v.gameId}`));
  if (games.size < legs.length && legs.length > 1) w.push({ level: "info", text: "Same-game legs: books price these parlays their own way, so compare carefully." });
  for (const c of new Set(found.map((f) => f.cat))) {
    for (const a of c.asOf) {
      if (a.at && now.getTime() - new Date(a.at).getTime() > STALE_HOURS * 3600_000) w.push({ level: "caution", text: `${a.label} last updated ${new Date(a.at).toUTCString().slice(5, 22)} UTC.` });
    }
  }
  return w;
}
