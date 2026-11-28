import "server-only";
import { loadBoard, loadPropsBoard } from "@/server/engine/board";
import { NFL_PREFIX, loadGameLines, loadPropLines, propLinesEnabled, ptDate, type DayView, type GameLinesView, type PlayerBookLines } from "@/server/markets/propLines";
import { americanToDecimal } from "@/lib/parlay/joint";
import type { BookPrice, BookQuote, GameCard, GameOption, LegOption, PropCard } from "@/lib/parlay/types";
import { coverProbs, gridAt, last10, overProbs, sigmaFromRange } from "@/lib/parlay/lines";
export { last10 };
import type { League } from "@/types/domain";
import type { EngineBoard, EngineGame } from "@/types/engine";
import type { EnginePropMarket, EnginePropPlayer, EnginePropsBoard } from "@/types/props";
import type { Variable } from "./correlations";
import { fetchEvent, type PmEvent } from "@/server/markets/polymarketLive";
import { isProduction } from "@/lib/auth-config";
import { contractsOf, gameContract, matchProps, sideQuote, type PmContract } from "./polymarket";
import { slugCodes } from "@/server/markets/polymarketLive";

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
  /** Present only with live Polymarket US data. */
  pm?: PmStats;
  /** One card per player per stat, and one per game market (the Parlay Builder's layout). */
  cards: Map<string, { props: PropCard[]; games: GameCard[] }>;
  /** Builds a leg the catalog didn't list in advance (any model threshold on the grid, any half/whole game line),
   *  from the same model distribution, with exact market matching. null when it can't be priced. */
  resolve: (id: string) => CatalogLeg | null;
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

const fmt1 = (x: number) => (Math.round(x * 10) / 10).toFixed(1);

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
  type Ctx = { g: EngineGame | null; pg: EnginePropsBoard["games"][number] | undefined; contracts: PmContract[] | null;
    pmLines?: Map<string, Map<number, PmContract>>; view: DayView | null; home: string; away: string };
  const ctxs = new Map<string, Ctx>();
  for (const g of upcoming) {
    const list: CatalogLeg[] = [];
    gameLines(league, g, gl, list);
    const pg = propGames.get(g.game_id);
    const pmg = pmFor(g.game_id, pg?.players ?? []);
    ctxs.set(g.game_id, { g, pg, contracts: pmg.contracts, pmLines: pmg.props?.lines, view: pg ? viewFor(pg.start_time) : null, home: g.home.abbr, away: g.away.abbr });
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
    ctxs.set(pg.game_id, { g: null, pg, contracts: pmg.contracts, pmLines: pmg.props?.lines, view: viewFor(pg.start_time), home: pg.home.abbr, away: pg.away.abbr });
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

  // ---------------------------------------------------------------- one card per player per stat, one per game market
  const cards = new Map<string, { props: PropCard[]; games: GameCard[] }>();
  const listedBy = new Map<string, string[]>();
  for (const k of legs.keys()) {
    const pre = k.split("~").slice(0, 5).join("~");
    if (k.split("~")[2] === "prop") (listedBy.get(pre) ?? listedBy.set(pre, []).get(pre)!).push(k);
  }
  for (const [gid, c] of ctxs) {
    const out = { props: [] as PropCard[], games: [] as GameCard[] };
    for (const pl of c.pg?.players ?? []) {
      if (/^out$/i.test(pl.injury_status ?? "")) continue;
      for (const [mkey, m] of Object.entries(pl.markets)) {
        if (m.support === "insufficient" || !m.grid) continue;
        const bl = mkey === BOOK_MARKET[league].market ? c.view?.games[gid]?.players[pl.player_id] : undefined;
        const pmc = [...(c.pmLines?.get(`${pl.player_id}|${mkey}`)?.values() ?? [])];
        const ks = new Set<number>();
        m.grid.p.forEach((p, i) => { if (p >= MIN_P && p <= MAX_P) ks.add(m.grid!.k0 + i * m.grid!.step); });
        for (const t of m.thresholds) if (t.op === ">=" && !t.variant && t.model_prob >= MIN_P && t.model_prob <= MAX_P) ks.add(t.threshold);
        for (const q of pmc) if (gridAt(m.grid, q.line!)) ks.add(q.line!);
        for (const b of bl?.books ?? []) if (Math.abs(b.line % 1) === 0.5 && gridAt(m.grid, b.line + 0.5)) ks.add(b.line + 0.5);
        out.props.push({
          key: `${gid}~${pl.player_id}~${mkey}`, league, gameId: gid, playerId: pl.player_id, playerName: pl.name, team: pl.team, opp: pl.opp ?? null,
          market: mkey, label: m.label, noun: m.label.toLowerCase(), projection: m.mean, grid: m.grid,
          ladder: Object.fromEntries(m.thresholds.filter((t) => t.op === ">=" && !t.variant).map((t) => [String(t.threshold), t.model_prob])),
          thresholds: [...ks].filter((k) => gridAt(m.grid, k) && !gridAt(m.grid, k)!.interpolated).sort((a, b) => a - b),
          bookLine: bl ? mainLine(bl.books) : null,
          quotes: (bl?.books ?? []).map((b) => ({ book: b.book, title: b.title, line: b.line, over: b.over, under: b.under, lastUpdate: b.last_update })),
          pm: pmc.map((q) => ({ line: q.line!, bid: q.bid, ask: q.ask, status: q.status, updatedAt: q.updatedAt })),
          pmFetchedAt: pmIn?.fetchedAt ?? null,
          values: (pl.recent?.values?.[mkey] ?? []).filter((x): x is number => typeof x === "number").slice(0, 10),
          injury: pl.injury_status, support: m.support, usage: usageOf(league, pl) ?? null,
          legIds: listedBy.get(`${league}~${gid}~prop~${pl.player_id}~${mkey}`) ?? [],
        });
      }
    }
    const g = c.g;
    if (g) {
      const pr = g.projection;
      const msd = sigmaFromRange(pr.margin_range_80);
      const tsd = sigmaFromRange(pr.total_range_80);
      const gb = Object.entries(gl?.games[gid]?.books ?? {});
      const pmc = c.contracts ?? [];
      const homeCodes = slugCodes(league, c.home);
      const awayCodes = slugCodes(league, c.away);
      // Polymarket team codes become "home" / "away" here, so the page never needs the slug rules.
      const sideOf = (t?: string): "home" | "away" | null => (t && homeCodes.includes(t) ? "home" : t && awayCodes.includes(t) ? "away" : null);
      const pmOut = (kind: string) => pmc.filter((x) => x.kind === kind && (kind === "total" || sideOf(x.team)))
        .map((x) => ({ team: kind === "total" ? null : sideOf(x.team), line: x.line, bid: x.bid, ask: x.ask, status: x.status, updatedAt: x.updatedAt }));
      // Model lines around the consensus (the engine's distribution supports any line); market lines are added below.
      const around = (c0: number, half: number) => Array.from({ length: half * 4 + 1 }, (_, i) => c0 + (i - half * 2) * 0.5);
      if (msd && g.market?.spread != null) {
        const lines = new Set<number>(around(g.market.spread, league === "nba" ? 4 : 3));
        for (const [, b] of gb) if (b.spread) lines.add(b.spread.line);
        for (const x of pmc) if (x.kind === "spread" && x.line !== null && sideOf(x.team)) lines.add(sideOf(x.team) === "home" ? x.line : -x.line);
        out.games.push({ league, gameId: gid, kind: "spread", home: c.home, away: c.away, consensus: g.market.spread, lines: [...lines].sort((a, b) => a - b),
          atConsensus: g.edges?.at_spread && Math.abs(g.edges.at_spread.line - g.market.spread) < 1e-9 ? { a: g.edges.at_spread.home.model_prob, b: g.edges.at_spread.away.model_prob, push: g.edges.at_spread.home.push_prob ?? 0 } : null,
          consensusPrice: g.edges?.at_spread && Math.abs(g.edges.at_spread.line - g.market.spread) < 1e-9 ? { a: g.edges.at_spread.home.market_price ?? null, b: g.edges.at_spread.away.market_price ?? null, books: g.market.books } : null,
          model: { mean: pr.margin, sd: msd }, books: gb.filter(([, b]) => b.spread).map(([k, b]) => ({ book: k, title: b.title, line: b.spread!.line, home: b.spread!.home, away: b.spread!.away, lastUpdate: b.spread!.last_update })),
          pm: pmOut("spread"), pmFetchedAt: pmIn?.fetchedAt ?? null });
      }
      if (tsd && g.market?.total != null) {
        const lines = new Set<number>(around(g.market.total, league === "nba" ? 6 : 4));
        for (const [, b] of gb) if (b.total) lines.add(b.total.line);
        for (const x of pmc) if (x.kind === "total" && x.line !== null) lines.add(x.line);
        out.games.push({ league, gameId: gid, kind: "total", home: c.home, away: c.away, consensus: g.market.total, lines: [...lines].sort((a, b) => a - b),
          atConsensus: g.edges?.at_total && Math.abs(g.edges.at_total.line - g.market.total) < 1e-9 ? { a: g.edges.at_total.over.model_prob, b: g.edges.at_total.under.model_prob, push: g.edges.at_total.over.push_prob ?? 0 } : null,
          consensusPrice: g.edges?.at_total && Math.abs(g.edges.at_total.line - g.market.total) < 1e-9 ? { a: g.edges.at_total.over.market_price ?? null, b: g.edges.at_total.under.market_price ?? null, books: g.market.books } : null,
          model: { mean: pr.total, sd: tsd }, books: gb.filter(([, b]) => b.total).map(([k, b]) => ({ book: k, title: b.title, line: b.total!.line, home: b.total!.over, away: b.total!.under, lastUpdate: b.total!.last_update })),
          pm: pmOut("total"), pmFetchedAt: pmIn?.fetchedAt ?? null });
      }
      if (g.edges?.moneyline) {
        out.games.push({ league, gameId: gid, kind: "moneyline", home: c.home, away: c.away, consensus: null, lines: [], atConsensus: null,
          consensusPrice: { a: g.edges.moneyline.home.market_price ?? null, b: g.edges.moneyline.away.market_price ?? null, books: g.market?.books ?? 0 },
          model: { homeWin: g.edges.moneyline.home.model_prob }, books: gb.filter(([, b]) => b.moneyline).map(([k, b]) => ({ book: k, title: b.title, line: null, home: b.moneyline!.home, away: b.moneyline!.away, lastUpdate: b.moneyline!.last_update })),
          pm: pmOut("moneyline"), pmFetchedAt: pmIn?.fetchedAt ?? null });
      }
    }
    cards.set(gid, out);
  }

  // ---------------------------------------------------------------- legs built on demand, from the same distributions
  const resolve = (id: string): CatalogLeg | null => {
    const hit = legs.get(id);
    if (hit) return hit;
    const parts = id.split("~");
    if (parts[0] !== league) return null;
    const gid = parts[1];
    const c = ctxs.get(gid);
    if (!c) return null;
    let made: CatalogLeg | null = null;
    if (parts[2] === "prop" && parts.length === 7) {
      const [, , , pid, mkey, tag, sd] = parts;
      if (!tag.startsWith("m") || (sd !== "o" && sd !== "u")) return null;      // book and Polymarket legs exist only when listed
      const K = Number(tag.slice(1));
      const pl = c.pg?.players.find((x) => x.player_id === pid);
      const m = pl?.markets[mkey];
      if (!pl || !m || m.support === "insufficient" || /^out$/i.test(pl.injury_status ?? "") || !Number.isFinite(K)) return null;
      const g0 = gridAt(m.grid, K);
      if (!g0 || g0.interpolated) return null;                              // model grid points only: no interpolation
      const side = sd === "o" ? 1 : -1;
      const lad = m.thresholds.find((t) => t.op === ">=" && !t.variant && t.threshold === K)?.model_prob;
      const pk = lad ?? g0.p;                                               // the published ladder value where there is one
      const p = side > 0 ? pk : 1 - pk;
      if (p < 0.005 || p > 0.995) return null;
      const noun = m.label.toLowerCase();
      const variable: Variable = { kind: "prop", league, gameId: gid, playerId: pid, market: mkey, team: pl.team, home: pl.team === c.home, pos: pl.position ?? null };
      const pmc = c.pmLines?.get(`${pid}|${mkey}`)?.get(K);
      made = { variable, side, option: { league, gameId: gid, kind: "prop", group: m.label, playerId: pid, playerName: pl.name, team: pl.team, support: m.support,
        injury: pl.injury_status, context: { opp: pl.opp, usage: usageOf(league, pl) }, id,
        label: side > 0 ? `${pl.name} ${K}+ ${noun}` : `${pl.name} under ${K} ${noun}`, p: r4(p), push: 0, price: null, marketP: null,
        source: "model_line", noPrice: `${NO_PRICE}: model line, not a sportsbook line`,
        ...(pmc && pmIn ? { polymarket: sideQuote(pmc, side > 0, pmIn.fetchedAt, `${pmc.title} ${noun}`) } : {}),
        last10: last10(pl.recent?.values?.[mkey], K, side, "atleast", noun, side > 0 ? `${m.label} ${K}+` : `${m.label} under ${K}`) } };
    } else if ((parts[2] === "spread" || parts[2] === "total") && parts.length === 5 && c.g) {
      const g = c.g;
      const L = Number(parts[4]);
      if (!Number.isFinite(L) || Math.abs(L * 2 - Math.round(L * 2)) > 1e-9) return null;
      const pr = g.projection;
      const bk = Object.entries(gl?.games[gid]?.books ?? {});
      if (parts[2] === "spread") {
        const sd = sigmaFromRange(pr.margin_range_80);
        const side = parts[3] === "home" ? "home" : parts[3] === "away" ? "away" : null;
        if (!sd || !side || Math.abs(L - (g.market?.spread ?? L)) > 20) return null;
        const cp = coverProbs(pr.margin, sd, L);
        const legLine = side === "home" ? L : -L;
        const quotes: BookQuote[] = bk.filter(([, b]) => b.spread).map(([k, b]) => ({ book: k, title: b.title, line: side === "home" ? b.spread!.line : -b.spread!.line,
          price: b.spread![side], other: b.spread![side === "home" ? "away" : "home"], lastUpdate: b.spread!.last_update }));
        const price = best(quotes, legLine);
        made = { variable: { kind: "margin", league, gameId: gid }, side: side === "home" ? 1 : -1, option: { league, gameId: gid, kind: "spread", group: "Game lines", id,
          label: `${g[side].abbr} ${fmt(legLine)}`, line: legLine, p: r4(side === "home" ? cp.home : cp.away), push: cp.push ? r4(cp.push) : 0,
          source: price ? "market_line" : "model_line", team: g[side].abbr, price, quotes, updatedAt: newest(quotes), marketP: noVig(quotes, legLine),
          noPrice: price ? null : `${NO_PRICE} at this line` } };
      } else {
        const sd = sigmaFromRange(pr.total_range_80);
        const side = parts[3] === "over" ? "over" : parts[3] === "under" ? "under" : null;
        if (!sd || !side || Math.abs(L - (g.market?.total ?? L)) > 30) return null;
        const op = overProbs(pr.total, sd, L);
        const quotes: BookQuote[] = bk.filter(([, b]) => b.total).map(([k, b]) => ({ book: k, title: b.title, line: b.total!.line,
          price: b.total![side], other: b.total![side === "over" ? "under" : "over"], lastUpdate: b.total!.last_update }));
        const price = best(quotes, L);
        made = { variable: { kind: "total", league, gameId: gid }, side: side === "over" ? 1 : -1, option: { league, gameId: gid, kind: "total", group: "Game lines", id,
          label: `${side === "over" ? "Over" : "Under"} ${L} total points`, line: L, p: r4(side === "over" ? op.over : op.under), push: op.push ? r4(op.push) : 0,
          source: price ? "market_line" : "model_line", price, quotes, updatedAt: newest(quotes), marketP: noVig(quotes, L),
          noPrice: price ? null : `${NO_PRICE} at this line` } };
      }
      if (made && c.contracts && pmIn) {
        const o = made.option;
        const team = o.kind === "total" ? null : o.team ?? null;
        const other = team === null ? null : team === c.home ? c.away : c.home;
        const hitc = gameContract(league, c.contracts, o.kind as "spread" | "total", team, other, o.line ?? null, made.side > 0);
        if (hitc) o.polymarket = sideQuote(hitc.c, hitc.yes, pmIn.fetchedAt, hitc.c.title);
      }
    }
    if (made) legs.set(id, made);
    return made;
  };
  return { league, games, legs, byGame, gameLabel, injuries, asOf, cards, resolve, ...(pmIn ? { pm: stats } : {}) };
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
