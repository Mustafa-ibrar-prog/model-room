import "server-only";
import { loadBoard, loadPropsBoard } from "@/server/engine/board";
import { loadPropLines, propLinesEnabled, ptDate, type DayView } from "@/server/markets/propLines";
import { americanToDecimal } from "@/lib/parlay/joint";
import type { BookPrice, GameOption, LegOption } from "@/lib/parlay/types";
import type { League } from "@/types/domain";
import type { EngineBoard, EngineGame } from "@/types/engine";
import type { EnginePropMarket, EnginePropPlayer, EnginePropsBoard } from "@/types/props";
import type { Variable } from "./correlations";

/**
 * Every leg the Parlay Builder can offer, built from what is already stored (TEST, Moose 2026-11-27):
 *   game lines  the consensus spread, total and moneyline on the league board, priced with the model's probabilities
 *               at those exact lines; moneyline prices as stored.
 *   NBA points  sportsbook lines captured to private R2 (TEST only), priced from the model's calibrated distribution.
 *   props       the model's own "at least K" thresholds (no sportsbook line; labelled as such).
 * Games that have started are not offered. Nothing here is estimated: a leg without data is left out.
 * Leg ids carry everything needed to re-derive the leg on the server, including the line, so a moved line is caught.
 */
export interface CatalogLeg { option: LegOption; variable: Variable; side: 1 | -1 }
export interface Catalog {
  league: League;
  games: GameOption[];
  legs: Map<string, CatalogLeg>;
  byGame: Map<string, LegOption[]>;
  gameLabel: Map<string, string>;
  injuries: Map<string, string[]>;
  asOf: { label: string; at: string | null }[];
}

const MIN_P = 0.03;
const MAX_P = 0.97;
const r4 = (x: number) => Math.round(x * 10000) / 10000;

export function legId(parts: (string | number)[]): string {
  return parts.map(String).join("~");
}

/** P(stat >= k) from the calibrated grid; linear between grid points (flagged); null outside the grid. */
export function gridP(m: EnginePropMarket, k: number): { p: number; interpolated: boolean } | null {
  const g = m.grid;
  if (!g || !g.p.length) return null;
  const idx = (k - g.k0) / g.step;
  if (idx < 0) return null;
  if (idx > g.p.length - 1) return null;
  const i = Math.floor(idx);
  const f = idx - i;
  if (f < 1e-9) return { p: g.p[i], interpolated: false };
  return { p: g.p[i] + f * (g.p[i + 1] - g.p[i]), interpolated: true };
}

/** Over / under a posted line L: half-point lines can't push; whole-number lines push at exactly L. */
export function linePs(m: EnginePropMarket, line: number) {
  const whole = Math.abs(line - Math.round(line)) < 1e-9;
  const kOver = whole ? Math.round(line) + 1 : Math.ceil(line);
  const over = gridP(m, kOver);
  const atLeastLine = whole ? gridP(m, Math.round(line)) : over;
  if (!over || !atLeastLine) return null;
  const push = whole ? Math.max(0, atLeastLine.p - over.p) : 0;
  return { over: over.p, under: Math.max(0, 1 - atLeastLine.p), push, interpolated: over.interpolated || atLeastLine.interpolated };
}

const started = (start: string | null, now: Date) => !start || new Date(start).getTime() <= now.getTime();
const gameText = (g: { away: { abbr: string }; home: { abbr: string } }) => `${g.away.abbr} @ ${g.home.abbr}`;

function bestPrice(books: { book: string; title: string; line: number; over: number | null; under: number | null; last_update: string | null }[], line: number, side: "over" | "under"): BookPrice | null {
  const at = books.filter((b) => Math.abs(b.line - line) < 1e-9 && b[side] !== null);
  if (!at.length) return null;
  const best = at.reduce((a, b) => (americanToDecimal(b[side]!) > americanToDecimal(a[side]!) ? b : a));
  return { american: best[side]!, book: best.book, bookTitle: best.title, books: at.length, capturedAt: best.last_update };
}

function gameLines(league: League, g: EngineGame, out: CatalogLeg[]) {
  const m = g.market;
  const e = g.edges;
  if (!m || !e) return;
  const base = { league, gameId: g.game_id };
  const margin: Variable = { kind: "margin", league, gameId: g.game_id };
  const total: Variable = { kind: "total", league, gameId: g.game_id };
  const fmt = (x: number) => (x > 0 ? `+${x}` : `${x}`);
  const priceOf = (american: number | null | undefined): BookPrice | null =>
    american == null ? null : { american, book: null, bookTitle: "Consensus", books: m.books, capturedAt: m.captured_at };
  if (m.spread != null && e.at_spread && Math.abs(e.at_spread.line - m.spread) < 1e-9) {
    for (const side of ["home", "away"] as const) {
      const s = e.at_spread[side];
      const line = side === "home" ? m.spread : -m.spread;
      out.push({
        variable: margin, side: side === "home" ? 1 : -1,
        option: { ...base, id: legId([league, g.game_id, "spread", side, m.spread]), kind: "spread", group: "Game lines",
          label: `${g[side].abbr} ${fmt(line)}`, p: r4(s.model_prob), push: s.push_prob ? r4(s.push_prob) : 0,
          price: priceOf(s.market_price), marketP: s.market_implied ?? null, source: "market_line", team: g[side].abbr },
      });
    }
  }
  if (m.total != null && e.at_total && Math.abs(e.at_total.line - m.total) < 1e-9) {
    for (const side of ["over", "under"] as const) {
      const s = e.at_total[side];
      out.push({
        variable: total, side: side === "over" ? 1 : -1,
        option: { ...base, id: legId([league, g.game_id, "total", side, m.total]), kind: "total", group: "Game lines",
          label: `${side === "over" ? "Over" : "Under"} ${m.total} total points`, p: r4(s.model_prob), push: s.push_prob ? r4(s.push_prob) : 0,
          price: priceOf(s.market_price), marketP: s.market_implied ?? null, source: "market_line" },
      });
    }
  }
  if (e.moneyline && (m.home_ml != null || m.away_ml != null)) {
    const novig = m.home_ml != null && m.away_ml != null
      ? (() => { const h = 1 / americanToDecimal(m.home_ml!); const a = 1 / americanToDecimal(m.away_ml!); return { home: h / (h + a), away: a / (h + a) }; })()
      : null;
    for (const side of ["home", "away"] as const) {
      const s = e.moneyline[side];
      out.push({
        variable: margin, side: side === "home" ? 1 : -1,
        option: { ...base, id: legId([league, g.game_id, "ml", side]), kind: "moneyline", group: "Game lines",
          label: `${g[side].abbr} to win`, p: r4(s.model_prob), push: s.push_prob ? r4(s.push_prob) : 0,
          price: priceOf(side === "home" ? m.home_ml : m.away_ml), marketP: novig ? r4(novig[side]) : null, source: "market_line", team: g[side].abbr },
      });
    }
  }
}

function playerLegs(league: League, gameId: string, homeAbbr: string, pl: EnginePropPlayer, view: DayView | null, out: CatalogLeg[]) {
  if (/^out$/i.test(pl.injury_status ?? "")) return;
  for (const [mkey, m] of Object.entries(pl.markets)) {
    if (m.support === "insufficient") continue;
    const variable: Variable = { kind: "prop", league, gameId, playerId: pl.player_id, market: mkey, team: pl.team, home: pl.team === homeAbbr, pos: pl.position ?? null };
    const common = { league, gameId, kind: "prop" as const, group: m.label, playerId: pl.player_id, playerName: pl.name, team: pl.team,
      support: m.support, injury: pl.injury_status };
    // Posted sportsbook line (NBA points, TEST only)
    const bl = league === "nba" && mkey === "points" ? view?.games[gameId]?.players[pl.player_id] : undefined;
    if (bl && bl.consensus_line != null) {
      const ps = linePs(m, bl.consensus_line);
      if (ps) {
        for (const side of ["over", "under"] as const) {
          const p = side === "over" ? ps.over : ps.under;
          if (p < MIN_P || p > MAX_P) continue;
          const mp = bl.consensus_over_novig == null ? null : side === "over" ? bl.consensus_over_novig : 1 - bl.consensus_over_novig;
          out.push({ variable, side: side === "over" ? 1 : -1, option: { ...common,
            id: legId([league, gameId, "prop", pl.player_id, mkey, `b${bl.consensus_line}`, side === "over" ? "o" : "u"]),
            label: `${pl.name} ${side} ${bl.consensus_line} points`, p: r4(p), push: ps.push ? r4(ps.push) : 0,
            price: bestPrice(bl.books, bl.consensus_line, side), marketP: mp == null ? null : r4(mp), source: "book_line", interpolated: ps.interpolated } });
        }
      }
    }
    // Model thresholds (no posted line)
    for (const t of m.thresholds) {
      if (t.op !== ">=" || t.variant) continue;
      for (const side of [1, -1] as const) {
        const p = side > 0 ? t.model_prob : 1 - t.model_prob;
        if (p < MIN_P || p > MAX_P) continue;
        const label = side > 0 ? `${pl.name} ${t.threshold}+ ${m.label.toLowerCase()}` : `${pl.name} under ${t.threshold} ${m.label.toLowerCase()}`;
        out.push({ variable, side, option: { ...common, id: legId([league, gameId, "prop", pl.player_id, mkey, `m${t.threshold}`, side > 0 ? "o" : "u"]),
          label, p: r4(p), push: 0, price: null, marketP: null, source: "model_line" } });
      }
    }
  }
}

/** Pure: the catalog from already-loaded inputs (tests call this directly). */
export function buildCatalog(league: League, board: EngineBoard | null, props: EnginePropsBoard | null, views: Record<string, DayView | null>, now: Date): Catalog {
  const legs = new Map<string, CatalogLeg>();
  const byGame = new Map<string, LegOption[]>();
  const games: GameOption[] = [];
  const gameLabel = new Map<string, string>();
  const injuries = new Map<string, string[]>();
  const propGames = new Map((props?.games ?? []).map((g) => [g.game_id, g]));
  const seen = new Set<string>();
  const upcoming = (board?.upcoming ?? []).filter((g) => !started(g.start_time, now));
  const add = (gid: string, list: CatalogLeg[]) => {
    for (const l of list) {
      legs.set(l.option.id, l);
      (byGame.get(gid) ?? byGame.set(gid, []).get(gid)!).push(l.option);
    }
  };
  for (const g of upcoming) {
    const list: CatalogLeg[] = [];
    gameLines(league, g, list);
    const pg = propGames.get(g.game_id);
    if (pg) for (const pl of pg.players) playerLegs(league, g.game_id, pg.home.abbr, pl, views[pg.start_time ? ptDate(pg.start_time) : ""] ?? null, list);
    add(g.game_id, list);
    seen.add(g.game_id);
    const lab = gameText(g);
    gameLabel.set(g.game_id, lab);
    games.push({ league, gameId: g.game_id, start: g.start_time, home: g.home.abbr, away: g.away.abbr, label: lab,
      props: Boolean(pg?.players.length), lines: list.some((l) => l.option.kind !== "prop") });
  }
  // Prop games the league board doesn't list yet
  for (const pg of props?.games ?? []) {
    if (seen.has(pg.game_id) || started(pg.start_time, now)) continue;
    const list: CatalogLeg[] = [];
    for (const pl of pg.players) playerLegs(league, pg.game_id, pg.home.abbr, pl, views[pg.start_time ? ptDate(pg.start_time) : ""] ?? null, list);
    add(pg.game_id, list);
    const lab = gameText(pg);
    gameLabel.set(pg.game_id, lab);
    games.push({ league, gameId: pg.game_id, start: pg.start_time, home: pg.home.abbr, away: pg.away.abbr, label: lab, props: pg.players.length > 0, lines: false });
  }
  for (const pg of props?.games ?? []) {
    const notes = pg.players.filter((p) => p.injury_status && !/^available$/i.test(p.injury_status)).map((p) => `${p.name} (${p.team}): ${p.injury_status}`);
    if (notes.length) injuries.set(pg.game_id, notes);
  }
  games.sort((a, b) => (a.start ?? "").localeCompare(b.start ?? ""));
  const asOf = [
    { label: `${league.toUpperCase()} game model and consensus lines`, at: board?.generated_at ?? null },
    { label: `${league.toUpperCase()} player model`, at: props?.generated_at ?? null },
    ...Object.entries(views).filter(([, v]) => v).map(([d, v]) => ({ label: `NBA points lines for ${d}`, at: v!.updated_at })),
  ];
  return { league, games, legs, byGame, gameLabel, injuries, asOf };
}

/** Loads the stored boards (and, on TEST, the stored NBA points lines) and builds the catalog. */
export async function getCatalog(league: League, now = new Date()): Promise<Catalog> {
  const [b, p] = await Promise.all([loadBoard(league), loadPropsBoard(league)]);
  const board = b.ok ? b.board : null;
  const props = p.ok ? p.board : null;
  const views: Record<string, DayView | null> = {};
  if (league === "nba" && propLinesEnabled()) {
    const dates = new Set((props?.games ?? []).filter((g) => !started(g.start_time, now)).filter((g) => g.start_time).map((g) => ptDate(g.start_time!)));
    for (const d of dates) views[d] = await loadPropLines(d);
  }
  return buildCatalog(league, board, props, views, now);
}
