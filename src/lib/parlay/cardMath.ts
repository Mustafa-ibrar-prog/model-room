/**
 * What a Parlay Builder card shows for the selected side and threshold (TEST, Moose 2026-11-27). Pure and shared: the
 * page runs it on every change for instant numbers; the server derives the same leg independently when it is added,
 * and tests check the two agree. Nothing here invents a line or a price: a market number appears only when a stored
 * sportsbook quote or a live Polymarket contract exists for exactly that outcome.
 */
import { americanToDecimal } from "./joint";
import { coverProbs, gridAt, last10, overProbs } from "./lines";
import type { GameCard, Last10, PropCard } from "./types";

export interface PmSide { bid: number | null; ask: number | null; implied: number | null; status: string; updatedAt: string | null }
export interface BookAt { american: number; title: string; books: number; line: number }
export interface Selection {
  p: number | null;
  push: number;
  label: string;
  book: BookAt | null;
  /** The books' own lines when none quotes this exact line (shown so nobody mistakes one for another). */
  otherBookLines: number[];
  pm: PmSide | null;
  /** Polymarket's own lines for this player and stat when none is at the selected threshold ("N+" thresholds). */
  otherPmLines: number[];
  /** Model minus market, in probability: Polymarket mid first, else the sportsbook no-vig. */
  gap: { vs: "Polymarket" | "sportsbook"; d: number } | null;
  marketP: number | null;
  last10: Last10 | null;
  /** Leg ids to try, best first (a listed sportsbook leg carries the book price; a model leg always exists). */
  ids: string[];
  /** The id this selection adds: the first of `ids` the catalog lists, else the model leg. */
  id: string;
}

const r4 = (x: number) => Math.round(x * 10000) / 10000;
const eq = (a: number | null | undefined, b: number | null | undefined) => a != null && b != null && Math.abs(a - b) < 1e-9;
const isHalf = (x: number) => Math.abs(Math.abs(x % 1) - 0.5) < 1e-9;

/** One side of a YES contract (the NO side mirrors the book). Same rule as the server's sideQuote. */
export function pmSide(c: { bid: number | null; ask: number | null; status: string; updatedAt: string | null }, yes: boolean): PmSide {
  const bid = yes ? c.bid : c.ask === null ? null : 1 - c.ask;
  const ask = yes ? c.ask : c.bid === null ? null : 1 - c.bid;
  const ok = bid !== null && ask !== null && bid <= ask + 1e-9 && c.status === "open";
  return { bid: bid === null ? null : r4(bid), ask: ask === null ? null : r4(ask), implied: ok ? r4((bid! + ask!) / 2) : null, status: c.status, updatedAt: c.updatedAt };
}

function bestAt(rows: { title: string; line: number | null; price: number | null; other: number | null }[], line: number | null) {
  const at = rows.filter((q) => q.price !== null && (line === null || eq(q.line, line)));
  if (!at.length) return { book: null, noVig: null };
  const b = at.reduce((x, y) => (americanToDecimal(y.price!) > americanToDecimal(x.price!) ? y : x));
  const nv = at.filter((q) => q.other !== null).map((q) => { const a = 1 / americanToDecimal(q.price!); const o = 1 / americanToDecimal(q.other!); return a / (a + o); }).sort((x, y) => x - y);
  const med = nv.length ? (nv.length % 2 ? nv[(nv.length - 1) / 2] : (nv[nv.length / 2 - 1] + nv[nv.length / 2]) / 2) : null;
  return { book: { american: b.price!, title: b.title, books: at.length, line: b.line ?? 0 }, noVig: med === null ? null : r4(med) };
}

function gapOf(p: number | null, pm: PmSide | null, nv: number | null): Selection["gap"] {
  if (p === null) return null;
  if (pm?.implied != null) return { vs: "Polymarket", d: p - pm.implied };
  if (nv !== null) return { vs: "sportsbook", d: p - nv };
  return null;
}

/** Player stat: "K or more" (side 1) or "under K" (side -1). A sportsbook line L counts only when L = K - 0.5. */
export function propSelection(c: PropCard, K: number, side: 1 | -1): Selection {
  const L = K - 0.5;
  const base = `${c.league}~${c.gameId}~prop~${c.playerId}~${c.market}`;
  const sd = side > 0 ? "o" : "u";
  const contract = c.pm.find((x) => eq(x.line, K));
  const ids = [...(eq(c.bookLine, L) ? [`${base}~b${L}~${sd}`] : []), ...(contract ? [`${base}~p${K}~${sd}`] : []), `${base}~m${K}~${sd}`];
  const chosen = ids.find((x) => c.legIds?.includes(x)) ?? ids[ids.length - 1];
  const g = gridAt(c.grid, K);
  // A model leg at a published ladder point uses the ladder's value; sportsbook and Polymarket legs read the grid.
  const pk = g && !g.interpolated ? (chosen.includes("~m") ? c.ladder?.[String(K)] ?? g.p : g.p) : null;
  const p = pk === null ? null : r4(side > 0 ? pk : 1 - pk);
  const rows = c.quotes.map((q) => ({ title: q.title, line: q.line, price: side > 0 ? q.over : q.under, other: side > 0 ? q.under : q.over }));
  const { book, noVig } = bestAt(rows, L);
  const pm = contract ? pmSide(contract, side > 0) : null;
  return {
    p, push: 0, label: side > 0 ? `${c.playerName} ${K}+ ${c.noun}` : `${c.playerName} under ${K} ${c.noun}`,
    book, otherBookLines: book ? [] : [...new Set(c.quotes.map((q) => q.line))].sort((a, b) => a - b),
    pm, otherPmLines: contract ? [] : c.pm.map((x) => x.line).sort((a, b) => a - b), gap: gapOf(p, pm, noVig), marketP: noVig,
    last10: last10(c.values ?? undefined, K, side, "atleast", c.noun, side > 0 ? `${c.label} ${K}+` : `${c.label} under ${K}`), ids, id: chosen,
  };
}

/** Game market. Spread: `line` is the HOME line, side 1 = home covers. Total: side 1 = over. Moneyline: side 1 = home. */
export function gameSelection(c: GameCard, line: number | null, side: 1 | -1): Selection {
  const base = `${c.league}~${c.gameId}`;
  const empty = { otherBookLines: [] as number[], otherPmLines: [] as number[], last10: null };
  if (c.kind === "moneyline" || !("mean" in c.model)) {
    const hw = "homeWin" in c.model ? c.model.homeWin : null;
    const p = hw === null ? null : r4(side > 0 ? hw : 1 - hw);
    const rows = c.books.map((b) => ({ title: b.title, line: null, price: side > 0 ? b.home : b.away, other: side > 0 ? b.away : b.home }));
    const { book: b0, noVig } = bestAt(rows, null);
    const cp = c.consensusPrice ? (side > 0 ? c.consensusPrice.a : c.consensusPrice.b) : null;
    const book = b0 ?? (cp === null ? null : { american: cp, title: "Consensus", books: c.consensusPrice!.books, line: 0 });
    const contract = c.pm.find((x) => x.team === (side > 0 ? "home" : "away"));
    const pm = contract ? pmSide(contract, true) : null;
    return { ...empty, p, push: 0, label: `${side > 0 ? c.home : c.away} to win`, book, pm, gap: gapOf(p, pm, noVig), marketP: noVig, ids: [`${base}~ml~${side > 0 ? "home" : "away"}`], id: `${base}~ml~${side > 0 ? "home" : "away"}` };
  }
  const L = line ?? c.consensus ?? 0;
  const { mean, sd } = c.model;
  let p: number, push: number, label: string, rows, id: string, pm: PmSide | null = null;
  // At the consensus line the engine's published numbers are used as they are (the listed leg uses them too).
  const at = eq(L, c.consensus) ? c.atConsensus : null;
  if (c.kind === "spread") {
    const cp = at ? { home: at.a, away: at.b, push: at.push } : coverProbs(mean, sd, L);
    p = side > 0 ? cp.home : cp.away;
    push = cp.push;
    const mine = side > 0 ? L : -L;
    label = `${side > 0 ? c.home : c.away} ${mine > 0 ? "+" : ""}${mine}`;
    rows = c.books.map((b) => ({ title: b.title, line: b.line, price: side > 0 ? b.home : b.away, other: side > 0 ? b.away : b.home }));
    const own = c.pm.find((x) => x.team === (side > 0 ? "home" : "away") && eq(x.line, mine));
    const opp = isHalf(L) ? c.pm.find((x) => x.team === (side > 0 ? "away" : "home") && eq(x.line, -mine)) : undefined;
    pm = own ? pmSide(own, true) : opp ? pmSide(opp, false) : null;
    id = `${base}~spread~${side > 0 ? "home" : "away"}~${L}`;
  } else {
    const op = at ? { over: at.a, under: at.b, push: at.push } : overProbs(mean, sd, L);
    p = side > 0 ? op.over : op.under;
    push = op.push;
    label = `${side > 0 ? "Over" : "Under"} ${L} total points`;
    rows = c.books.map((b) => ({ title: b.title, line: b.line, price: side > 0 ? b.home : b.away, other: side > 0 ? b.away : b.home }));
    const t = c.pm.find((x) => eq(x.line, L));
    pm = t && (side > 0 || isHalf(L)) ? pmSide(t, side > 0) : null;
    id = `${base}~total~${side > 0 ? "over" : "under"}~${L}`;
  }
  // The engine's book rows are home-perspective for spreads; a book quote counts only at exactly this line.
  const { book: b0, noVig } = bestAt(rows, L);
  const cp = at && c.consensusPrice ? (side > 0 ? c.consensusPrice.a : c.consensusPrice.b) : null;
  const book = b0 ?? (cp === null ? null : { american: cp, title: "Consensus", books: c.consensusPrice!.books, line: L });
  const pr = r4(p);
  return { ...empty, p: pr, push: push ? r4(push) : 0, label, book: book && c.kind === "spread" ? { ...book, line: side > 0 ? book.line : -book.line } : book,
    otherBookLines: book ? [] : [...new Set(c.books.map((b) => b.line).filter((x): x is number => x !== null))].sort((a, b) => a - b),
    pm, gap: gapOf(pr, pm, noVig), marketP: noVig, ids: [id], id };
}
