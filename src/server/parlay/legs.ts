import "server-only";
import { loadBoard, loadPropsBoard } from "@/server/engine/board";
import { NFL_PREFIX, loadGameLines, loadPropLines, propLinesEnabled, ptDate, type DayView, type GameLinesView, type PlayerBookLines } from "@/server/markets/propLines";
import { americanToDecimal } from "@/lib/parlay/joint";
import type { BookPrice, BookQuote, GameOption, Last10, LegOption } from "@/lib/parlay/types";
import type { League } from "@/types/domain";
import type { EngineBoard, EngineGame } from "@/types/engine";
import type { EnginePropMarket, EnginePropPlayer, EnginePropsBoard } from "@/types/props";
import type { Variable } from "./correlations";
import { fetchEvent, type PmEvent } from "@/server/markets/polymarketLive";
import { isProduction } from "@/lib/auth-config";
import { contractsOf, gameContract, matchProps, sideQuote, type PmContract } from "./polymarket";

export interface PmInput { events: Map<string, PmEvent>; fetchedAt: string }
export interface PmStats { games: number; eventsFound: number; contracts: number; matchedProps: number; legsWithQuote: number; exchangeLegs: number;
  skipped: { ambiguous: number; teamMismatch: number; notOnBoard: number } }

/**
 * Every leg the Parlay Builder can offer, built from what is already stored (TEST, Moose 2026-11-27):
 *   game lines  the consensus spread / total / moneyline on the league board, priced with the model's probabilities at
 *               those exact lines; each sportsbook's own line and prices from private R2 (sources/gamelines_r2.py).
 *   book props  NBA points and NFL receiving yards at the line most books posted (private R2), every book's quote kept.
 *   model props the model's own "at least K" thresholds: never shown as a sportsbook line.
 * Every prop leg carries the player's last 10 played games against its exact line (box scores from the board).
 * Games that have started are not offered. Nothing is estimated: a leg without data is left out; a leg without a
 * price says so in words.
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
  /** Present only in the private view with live Polymarket US data. */
  pm?: PmStats;
}

/** The prop market each league's stored sportsbook lines cover (one market per game: the free-plan budget). */
export const BOOK_MARKET: Record<League, { market: string; noun: string }> = {
  nba: { market: "points", noun: "points" },
  nfl: { market: "receiving_yards", noun: "receiving yards" },
};
export const NO_PRICE = "No sportsbook price available";

const MIN_P = 0.03;
const MAX_P = 0.97;
const r4 = (x: number) => Math.round(x * 10000) / 10000;
const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

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

/** The line the most books posted (ties: nearest the median line, then the lower). A real posted line, never a median. */
export function mainLine(books: { line: number }[]): number | null {
  if (!books.length) return null;
  const count = new Map<number, number>();
  for (const b of books) count.set(b.line, (count.get(b.line) ?? 0) + 1);
  const med = median(books.map((b) => b.line))!;
  return [...count.entries()].sort((a, b) => b[1] - a[1] || Math.abs(a[0] - med) - Math.abs(b[0] - med) || a[0] - b[0])[0][0];
}

function best(quotes: BookQuote[], line: number | null): BookPrice | null {
  const at = quotes.filter((q) => q.price !== null && (line === null || (q.line !== null && Math.abs(q.line - line) < 1e-9)));
  if (!at.length) return null;
  const b = at.reduce((x, y) => (americanToDecimal(y.price!) > americanToDecimal(x.price!) ? y : x));
  return { american: b.price!, book: b.book, bookTitle: b.title, books: at.length, capturedAt: b.lastUpdate };
}

/** Median no-vig probability for this side across books quoting this exact line with both prices. */
function noVig(quotes: BookQuote[], line: number | null): number | null {
  const ps = quotes
    .filter((q) => q.price !== null && q.other !== null && (line === null || (q.line !== null && Math.abs(q.line - line) < 1e-9)))
    .map((q) => { const a = 1 / americanToDecimal(q.price!); const b = 1 / americanToDecimal(q.other!); return a / (a + b); });
  const m = median(ps);
  return m === null ? null : r4(m);
}
const newest = (quotes: BookQuote[]) => quotes.reduce<string | null>((a, q) => (q.lastUpdate && (!a || q.lastUpdate > a) ? q.lastUpdate : a), null);

// ------------------------------------------------------------------------------------------------- last 10
const fmt1 = (x: number) => (Math.round(x * 10) / 10).toFixed(1);

/**
 * The player's last 10 played games (newest first, from the board's box scores) against this exact line.
 *   book line L, over:  win above L, push at exactly L (whole-number lines only), loss below
 *   model "K+":        win at K or more; "under K": win below K (no pushes)
 * null when the board has no game log for this stat (never invented).
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

function usageOf(league: League, pl: EnginePropPlayer): string | undefined {
  const g = (pl.recent?.games ?? []).slice(0, 5);
  if (!g.length) return undefined;
  const avg = (k: string) => {
    const xs = g.map((x) => x[k]).filter((x): x is number => typeof x === "number");
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  };
  if (league === "nba") {
    const m = avg("minutes");
    return m === null ? undefined : `${fmt1(m)} minutes a game over his last ${g.length}`;
  }
  const snaps = avg("snap_pct");
  const t = avg("targets");
  const parts = [snaps !== null ? `${Math.round(snaps)}% of snaps` : null, t !== null && t > 0 ? `${fmt1(t)} targets` : null].filter(Boolean);
  return parts.length ? `${parts.join(", ")} a game over his last ${g.length}` : undefined;
}

// ------------------------------------------------------------------------------------------------- builders
const started = (start: string | null, now: Date) => !start || new Date(start).getTime() <= now.getTime();
const gameText = (g: { away: { abbr: string }; home: { abbr: string } }) => `${g.away.abbr} @ ${g.home.abbr}`;
const fmt = (x: number) => (x > 0 ? `+${x}` : `${x}`);

function gameLines(league: League, g: EngineGame, gl: GameLinesView | null, out: CatalogLeg[]) {
  const m = g.market;
  const e = g.edges;
  if (!m || !e) return;
  const base = { league, gameId: g.game_id };
  const margin: Variable = { kind: "margin", league, gameId: g.game_id };
  const total: Variable = { kind: "total", league, gameId: g.game_id };
  const books = Object.entries(gl?.games[g.game_id]?.books ?? {});
  const withQuotes = (quotes: BookQuote[], line: number | null, fallback: number | null | undefined) => {
    const price = best(quotes, line) ?? (fallback == null ? null : { american: fallback, book: null, bookTitle: "Consensus", books: m.books, capturedAt: m.captured_at });
    const sameLine = line === null || quotes.some((q) => q.line !== null && Math.abs(q.line - line) < 1e-9);
    return {
      price, quotes, updatedAt: newest(quotes) ?? m.captured_at, marketP: noVig(quotes, line),
      noPrice: price ? null : quotes.length && !sameLine ? `${NO_PRICE} at exactly this line (it's the median of ${m.books} books); see each book's own line` : NO_PRICE,
    };
  };
  if (m.spread != null && e.at_spread && Math.abs(e.at_spread.line - m.spread) < 1e-9) {
    for (const side of ["home", "away"] as const) {
      const s = e.at_spread[side];
      const line = side === "home" ? m.spread : -m.spread;
      const quotes: BookQuote[] = books.filter(([, b]) => b.spread).map(([k, b]) => ({
        book: k, title: b.title, line: side === "home" ? b.spread!.line : -b.spread!.line,
        price: b.spread![side], other: b.spread![side === "home" ? "away" : "home"], lastUpdate: b.spread!.last_update }));
      out.push({ variable: margin, side: side === "home" ? 1 : -1, option: { ...base, id: legId([league, g.game_id, "spread", side, m.spread]), kind: "spread",
        group: "Game lines", label: `${g[side].abbr} ${fmt(line)}`, line, p: r4(s.model_prob), push: s.push_prob ? r4(s.push_prob) : 0, source: "market_line",
        team: g[side].abbr, ...withQuotes(quotes, line, s.market_price) } });
    }
  }
  if (m.total != null && e.at_total && Math.abs(e.at_total.line - m.total) < 1e-9) {
    for (const side of ["over", "under"] as const) {
      const s = e.at_total[side];
      const quotes: BookQuote[] = books.filter(([, b]) => b.total).map(([k, b]) => ({
        book: k, title: b.title, line: b.total!.line, price: b.total![side], other: b.total![side === "over" ? "under" : "over"], lastUpdate: b.total!.last_update }));
      out.push({ variable: total, side: side === "over" ? 1 : -1, option: { ...base, id: legId([league, g.game_id, "total", side, m.total]), kind: "total",
        group: "Game lines", label: `${side === "over" ? "Over" : "Under"} ${m.total} total points`, line: m.total, p: r4(s.model_prob), push: s.push_prob ? r4(s.push_prob) : 0,
        source: "market_line", ...withQuotes(quotes, m.total, s.market_price) } });
    }
  }
  if (e.moneyline) {
    for (const side of ["home", "away"] as const) {
      const s = e.moneyline[side];
      const quotes: BookQuote[] = books.filter(([, b]) => b.moneyline).map(([k, b]) => ({
        book: k, title: b.title, line: null, price: b.moneyline![side], other: b.moneyline![side === "home" ? "away" : "home"], lastUpdate: b.moneyline!.last_update }));
      const consensus = side === "home" ? m.home_ml : m.away_ml;
      const w = withQuotes(quotes, null, consensus);
      if (w.marketP === null && m.home_ml != null && m.away_ml != null) {
        const h = 1 / americanToDecimal(m.home_ml), a = 1 / americanToDecimal(m.away_ml);
        w.marketP = r4((side === "home" ? h : a) / (h + a));
      }
      out.push({ variable: margin, side: side === "home" ? 1 : -1, option: { ...base, id: legId([league, g.game_id, "ml", side]), kind: "moneyline",
        group: "Game lines", label: `${g[side].abbr} to win`, p: r4(s.model_prob), push: s.push_prob ? r4(s.push_prob) : 0, source: "market_line",
        team: g[side].abbr, ...w } });
    }
  }
}

function bookQuotes(bl: PlayerBookLines, side: "over" | "under"): BookQuote[] {
  return bl.books.map((b) => ({ book: b.book, title: b.title, line: b.line, price: b[side], other: b[side === "over" ? "under" : "over"], lastUpdate: b.last_update }));
}

function playerLegs(league: League, gameId: string, homeAbbr: string, pl: EnginePropPlayer, view: DayView | null, out: CatalogLeg[],
  pm?: { lines: Map<string, Map<number, PmContract>>; fetchedAt: string; stats: PmStats }) {
  if (/^out$/i.test(pl.injury_status ?? "")) return;
  const context = { opp: pl.opp, usage: usageOf(league, pl) };
  for (const [mkey, m] of Object.entries(pl.markets)) {
    if (m.support === "insufficient") continue;
    const variable: Variable = { kind: "prop", league, gameId, playerId: pl.player_id, market: mkey, team: pl.team, home: pl.team === homeAbbr, pos: pl.position ?? null };
    const common = { league, gameId, kind: "prop" as const, group: m.label, playerId: pl.player_id, playerName: pl.name, team: pl.team,
      support: m.support, injury: pl.injury_status, context };
    const noun = m.label.toLowerCase();
    const values = pl.recent?.values?.[mkey];
    const marketStart = out.length;
    // Posted sportsbook line (NBA points / NFL receiving yards, TEST only)
    const bl = mkey === BOOK_MARKET[league].market ? view?.games[gameId]?.players[pl.player_id] : undefined;
    const line = bl ? mainLine(bl.books) : null;
    if (bl && line !== null) {
      const ps = linePs(m, line);
      if (ps) {
        for (const side of ["over", "under"] as const) {
          const p = side === "over" ? ps.over : ps.under;
          if (p < MIN_P || p > MAX_P) continue;
          const quotes = bookQuotes(bl, side);
          const price = best(quotes, line);
          const label = `${pl.name} ${side} ${line} ${noun}`;
          out.push({ variable, side: side === "over" ? 1 : -1, option: { ...common,
            id: legId([league, gameId, "prop", pl.player_id, mkey, `b${line}`, side === "over" ? "o" : "u"]),
            label, line, p: r4(p), push: ps.push ? r4(ps.push) : 0, price, quotes, updatedAt: newest(quotes), marketP: noVig(quotes, line),
            noPrice: price ? null : NO_PRICE, source: "book_line", interpolated: ps.interpolated,
            last10: last10(values, line, side === "over" ? 1 : -1, "line", noun, `${m.label} ${side === "over" ? "Over" : "Under"} ${line}`) } });
        }
      }
    }
    // Model thresholds: never a sportsbook line
    for (const t of m.thresholds) {
      if (t.op !== ">=" || t.variant) continue;
      for (const side of [1, -1] as const) {
        const p = side > 0 ? t.model_prob : 1 - t.model_prob;
        if (p < MIN_P || p > MAX_P) continue;
        const label = side > 0 ? `${pl.name} ${t.threshold}+ ${noun}` : `${pl.name} under ${t.threshold} ${noun}`;
        out.push({ variable, side, option: { ...common, id: legId([league, gameId, "prop", pl.player_id, mkey, `m${t.threshold}`, side > 0 ? "o" : "u"]),
          label, p: r4(p), push: 0, price: null, marketP: null, source: "model_line", noPrice: `${NO_PRICE}: model line, not a sportsbook line`,
          last10: last10(values, t.threshold, side, "atleast", noun, side > 0 ? `${m.label} ${t.threshold}+` : `${m.label} under ${t.threshold}`) } });
      }
    }
    // Polymarket US (private view): exact contracts only. "N+" = at least N = over N-0.5; NO side = fewer than N.
    const pml = pm?.lines.get(`${pl.player_id}|${mkey}`);
    if (pm && pml) {
      const have = new Set<number>();
      for (const leg of out.slice(marketStart)) {
        const parts = leg.option.id.split("~");
        const tag = parts[5];
        const n = tag.startsWith("m") ? Number(tag.slice(1)) : tag.startsWith("b") && Math.abs((Number(tag.slice(1)) % 1) - 0.5) < 1e-9 ? Number(tag.slice(1)) + 0.5 : NaN;
        const c = Number.isFinite(n) ? pml.get(n) : undefined;
        if (!c) continue;
        if (tag.startsWith("m")) have.add(n);
        leg.option.polymarket = sideQuote(c, leg.side > 0, pm.fetchedAt, `${c.title} ${noun}`);
        pm.stats.legsWithQuote++;
      }
      for (const [n, c] of pml) {
        if (have.has(n)) continue;
        const g = gridP(m, n);
        if (!g) continue;
        for (const side of [1, -1] as const) {
          const p = side > 0 ? g.p : 1 - g.p;
          if (p < MIN_P || p > MAX_P) continue;
          const label = side > 0 ? `${pl.name} ${n}+ ${noun}` : `${pl.name} under ${n} ${noun}`;
          out.push({ variable, side, option: { ...common, id: legId([league, gameId, "prop", pl.player_id, mkey, `p${n}`, side > 0 ? "o" : "u"]),
            label, p: r4(p), push: 0, price: null, marketP: null, source: "exchange_line", interpolated: g.interpolated,
            noPrice: `${NO_PRICE}: Polymarket contract line`, polymarket: sideQuote(c, side > 0, pm.fetchedAt, `${c.title} ${noun}`),
            last10: last10(values, n, side, "atleast", noun, side > 0 ? `${m.label} ${n}+` : `${m.label} under ${n}`) } });
          pm.stats.exchangeLegs++;
          pm.stats.legsWithQuote++;
        }
      }
    }
  }
}

/** Pure: the catalog from already-loaded inputs (tests call this directly). */
export function buildCatalog(league: League, board: EngineBoard | null, props: EnginePropsBoard | null, views: Record<string, DayView | null>, now: Date,
  gl: GameLinesView | null = null, pmIn: PmInput | null = null): Catalog {
  const stats: PmStats = { games: 0, eventsFound: 0, contracts: 0, matchedProps: 0, legsWithQuote: 0, exchangeLegs: 0, skipped: { ambiguous: 0, teamMismatch: 0, notOnBoard: 0 } };
  const pmFor = (gid: string, players: EnginePropPlayer[]) => {
    if (!pmIn) return { contracts: null as PmContract[] | null, props: undefined };
    stats.games++;
    const ev = pmIn.events.get(gid);
    if (!ev) return { contracts: null, props: undefined };
    stats.eventsFound++;
    const contracts = contractsOf(ev);
    stats.contracts += contracts.length;
    const mt = matchProps(league, contracts, players.map((p) => ({ playerId: p.player_id, name: p.name, team: p.team })));
    stats.matchedProps += mt.matched;
    stats.skipped.ambiguous += mt.skipped.ambiguous;
    stats.skipped.teamMismatch += mt.skipped.teamMismatch;
    stats.skipped.notOnBoard += mt.skipped.notOnBoard;
    return { contracts, props: { lines: mt.byPlayerMarket, fetchedAt: pmIn.fetchedAt, stats } };
  };
  const attachGame = (list: CatalogLeg[], contracts: PmContract[] | null, home: string, away: string) => {
    if (!contracts || !pmIn) return;
    for (const l of list) {
      const o = l.option;
      if (o.kind === "prop") continue;
      const team = o.kind === "total" ? null : o.team ?? null;
      const other = team === null ? null : team === home ? away : home;
      const hit = gameContract(league, contracts, o.kind, team, other, o.kind === "moneyline" ? null : o.line ?? null, l.side > 0);
      if (!hit) continue;
      o.polymarket = sideQuote(hit.c, hit.yes, pmIn.fetchedAt, hit.c.title);
      stats.legsWithQuote++;
    }
  };
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
  const viewFor = (start: string | null) => (start ? views[ptDate(start)] ?? null : null);
  for (const g of upcoming) {
    const list: CatalogLeg[] = [];
    gameLines(league, g, gl, list);
    const pg = propGames.get(g.game_id);
    const pmg = pmFor(g.game_id, pg?.players ?? []);
    attachGame(list, pmg.contracts, g.home.abbr, g.away.abbr);
    if (pg) for (const pl of pg.players) playerLegs(league, g.game_id, pg.home.abbr, pl, viewFor(pg.start_time), list, pmg.props);
    add(g.game_id, list);
    seen.add(g.game_id);
    const lab = gameText(g);
    gameLabel.set(g.game_id, lab);
    games.push({ league, gameId: g.game_id, start: g.start_time, home: g.home.abbr, away: g.away.abbr, label: lab,
      props: Boolean(pg?.players.length), lines: list.some((l) => l.option.kind !== "prop") });
  }
  for (const pg of props?.games ?? []) {
    if (seen.has(pg.game_id) || started(pg.start_time, now)) continue;
    const list: CatalogLeg[] = [];
    const pmg = pmFor(pg.game_id, pg.players);
    for (const pl of pg.players) playerLegs(league, pg.game_id, pg.home.abbr, pl, viewFor(pg.start_time), list, pmg.props);
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
    { label: `${league.toUpperCase()} game model`, at: board?.generated_at ?? null },
    { label: `${league.toUpperCase()} sportsbook game lines`, at: gl?.generated_at ?? null },
    { label: `${league.toUpperCase()} player model`, at: props?.generated_at ?? null },
    ...Object.entries(views).filter(([, v]) => v).map(([d, v]) => ({ label: `${league.toUpperCase()} ${BOOK_MARKET[league].noun} lines for ${d}`, at: v!.updated_at })),
  ];
  if (pmIn) asOf.push({ label: `${league.toUpperCase()} Polymarket US prices (live, not stored)`, at: pmIn.fetchedAt });
  return { league, games, legs, byGame, gameLabel, injuries, asOf, ...(pmIn ? { pm: stats } : {}) };
}

/** Loads the stored boards and, on TEST, the stored sportsbook lines (private R2), and builds the catalog. */
export async function getCatalog(league: League, now = new Date(), opts: { live?: boolean } = {}): Promise<Catalog> {
  const [b, p] = await Promise.all([loadBoard(league), loadPropsBoard(league)]);
  const board = b.ok ? b.board : null;
  const props = p.ok ? p.board : null;
  const views: Record<string, DayView | null> = {};
  let gl: GameLinesView | null = null;
  if (propLinesEnabled()) {
    const dates = new Set((props?.games ?? []).filter((g) => g.start_time && !started(g.start_time, now)).map((g) => ptDate(g.start_time!)));
    const prefix = league === "nba" ? undefined : NFL_PREFIX;
    await Promise.all([...dates].map(async (d) => { views[d] = await loadPropLines(d, prefix); }));
    gl = await loadGameLines(league);
  }
  let pmIn: PmInput | null = null;
  if (opts.live && !isProduction()) {
    // Private view: games in the next day (NBA) or 8 days (NFL); a few requests at a time; 60 s cache per event.
    const horizon = now.getTime() + (league === "nba" ? 36 : 8 * 24) * 3600_000;
    const want = (board?.upcoming ?? []).filter((g) => g.start_time && !started(g.start_time, now) && new Date(g.start_time).getTime() <= horizon).slice(0, 20);
    const events = new Map<string, PmEvent>();
    for (let i = 0; i < want.length; i += 4) {
      const part = want.slice(i, i + 4);
      const evs = await Promise.all(part.map((g) => fetchEvent(league, g.game_id, g.away.abbr, g.home.abbr, g.game_date)));
      part.forEach((g, j) => evs[j] && events.set(g.game_id, evs[j]!));
    }
    pmIn = { events, fetchedAt: now.toISOString() };
  }
  return buildCatalog(league, board, props, views, now, gl, pmIn);
}
