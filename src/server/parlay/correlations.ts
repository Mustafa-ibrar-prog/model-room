import "server-only";
import { readFileSync } from "node:fs";
import path from "node:path";
import { publishedDir } from "@/server/engine/board";
import type { League } from "@/types/domain";

/**
 * The historical correlation table (modeling/modelroom/parlay/correlations.py → data/published/parlay_correlations.json)
 * and the rules that turn two parlay variables into one coefficient. Server only: the table is aggregate statistics, not
 * model weights, but there is no reason to ship it to browsers.
 */
export interface Cell { r: number | null; lo: number | null; hi: number | null; n: number; n_eff: number; insufficient: boolean }
interface LeagueTable {
  cells: Record<string, Cell>;
  cross_game: { independent: boolean; engine_r_band: number | null; cells: Record<string, Cell> };
  estimation_seasons: number[];
}
export interface Table { built_at: string; min_pairs: number; leagues: Record<League, LeagueTable> }

/** A latent variable a leg sits on. Spread and moneyline legs share the game's home margin. */
export type Variable =
  | { kind: "prop"; league: League; gameId: string; playerId: string; market: string; team: string; home: boolean; pos: string | null }
  | { kind: "margin"; league: League; gameId: string }
  | { kind: "total"; league: League; gameId: string };

export function variableKey(v: Variable): string {
  return v.kind === "prop" ? `${v.league}~${v.gameId}~p~${v.playerId}~${v.market}` : `${v.league}~${v.gameId}~${v.kind}`;
}

let cached: { at: number; table: Table | null } | null = null;
export function loadTable(): Table | null {
  if (cached && Date.now() - cached.at < 10 * 60_000) return cached.table;
  let table: Table | null = null;
  try {
    const t = JSON.parse(readFileSync(path.join(publishedDir(), "parlay_correlations.json"), "utf8"));
    if (t?.kind === "parlay_correlations" && t.schema === 1) table = t as Table;
  } catch {
    table = null;
  }
  cached = { at: Date.now(), table };
  return table;
}
export function setTableForTests(t: Table | null) {
  cached = { at: Date.now(), table: t };
}

const key = (rel: string, a: string, b?: string) => (b === undefined ? `${rel}|${a}` : a <= b ? `${rel}|${a}|${b}` : `${rel}|${b}|${a}`);
const label = (v: Extract<Variable, { kind: "prop" }>) => (v.league === "nfl" ? `${v.pos ?? "?"}:${v.market}` : v.market);

export interface Relation { r: number; lo: number; hi: number; relation: string }

/**
 * Coefficient between two variables (oriented: more points, home team doing better, more total points), with its 95%
 * interval. null = not measured with enough data: the caller must fall back to bounds, never guess.
 */
export function relate(t: Table, a: Variable, b: Variable): Relation | null {
  if (a.league !== b.league) return { r: 0, lo: 0, hi: 0, relation: "different sports" };
  const L = t.leagues[a.league];
  if (!L) return null;
  if (a.gameId !== b.gameId) {
    const band = L.cross_game.engine_r_band ?? 0;
    if (L.cross_game.independent) return { r: 0, lo: -band, hi: band, relation: "different games" };
    if (a.kind === "prop" && b.kind === "prop") return fromCell(L.cross_game.cells[key("xgame", a.market, b.market)], 1, "different games");
    if (a.kind === "total" && b.kind === "total") return fromCell(L.cross_game.cells["xgame|total|total"], 1, "different games");
    return { r: 0, lo: -band, hi: band, relation: "different games" };
  }
  if (a.kind === "prop" && b.kind === "prop") {
    if (a.playerId === b.playerId) return a.market === b.market ? { r: 1, lo: 1, hi: 1, relation: "same stat" } : fromCell(L.cells[key("same", a.market, b.market)], 1, "same player");
    const rel = a.team === b.team ? "team" : "opp";
    return fromCell(L.cells[key(rel, label(a), label(b))], 1, rel === "team" ? "teammates" : "opponents");
  }
  if (a.kind === "prop" || b.kind === "prop") {
    const p = (a.kind === "prop" ? a : b) as Extract<Variable, { kind: "prop" }>;
    const g = a.kind === "prop" ? b : a;
    if (g.kind === "total") return fromCell(L.cells[key("ptotal", label(p))], 1, "player and game total");
    return fromCell(L.cells[key("pmargin", label(p))], p.home ? 1 : -1, "player and game result");
  }
  if (a.kind === b.kind) return { r: 1, lo: 1, hi: 1, relation: "same line" };
  return fromCell(L.cells["game|margin|total"], 1, "game result and total");
}

function fromCell(c: Cell | undefined, sign: 1 | -1, relation: string): Relation | null {
  if (!c || c.insufficient || c.r === null || c.lo === null || c.hi === null) return null;
  return sign > 0 ? { r: c.r, lo: c.lo, hi: c.hi, relation } : { r: -c.r, lo: -c.hi, hi: -c.lo, relation };
}
