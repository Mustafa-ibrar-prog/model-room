import "server-only";
import { isProduction, isTestAccount } from "@/lib/auth-config";
import { getSessionUser } from "@/server/session";
import type { League } from "@/types/domain";
import type { EngineBestSide, EnginePropsBoard, EngineQuoteView, EngineThreshold } from "@/types/props";

/**
 * Owner-only live Polymarket US prices on the TEST SITE.
 *
 * Polymarket's prices aren't cleared for publication yet, so they are never written to the repo, a
 * board file or a database. This module fetches the public, read-only gateway at request time (server
 * side) and only for the site owner's login, and only outside production. Everyone else, and every
 * production request, gets the board exactly as published.
 *
 * Who counts as the owner: an address in OWNER_EMAILS (comma-separated, server env), or, when that
 * isn't set, the @modelroom.test accounts. MODELROOM_OWNER_LIVE_MARKETS=off switches it off entirely.
 */

const BASE = "https://gateway.polymarket.us";
const PROVIDER = "polymarket_us";
const TTL_MS = 60_000;         // a found event is reused for a minute
const MISS_TTL_MS = 10 * 60_000; // a slug that 404'd isn't retried for ten minutes
const TIMEOUT_MS = 4_000;
const MAX_SPREAD = 0.06;
const MIN_EV = 0.02;

export async function ownerLiveMarkets(): Promise<boolean> {
  if (isProduction() || process.env.MODELROOM_OWNER_LIVE_MARKETS === "off") return false;
  const user = await getSessionUser();
  const email = user?.email?.toLowerCase();
  if (!email) return false;
  const list = (process.env.OWNER_EMAILS ?? "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  return list.length ? list.includes(email) : isTestAccount(email);
}

// ------------------------------------------------------------------ fetching
const SLUG_CODES: Record<League, Record<string, string[]>> = {
  nfl: { LA: ["lar", "la"], JAX: ["jax", "jac"], WAS: ["was", "wsh"] },
  nba: { GS: ["gsw", "gs"], NY: ["nyk", "ny"], NO: ["nop", "no"], SA: ["sas", "sa"], UTAH: ["uta", "utah"], WSH: ["was", "wsh"], PHX: ["phx", "pho"], BKN: ["bkn", "brk"] },
};
export const slugCodes = (league: League, code: string) => SLUG_CODES[league][code] ?? [code.toLowerCase()];

export function candidateSlugs(league: League, away: string, home: string, date: string): string[] {
  const out: string[] = [];
  for (const a of slugCodes(league, away)) for (const h of slugCodes(league, home)) out.push(`${league}-${a}-${h}-${date}`, `${league}-${h}-${a}-${date}`);
  return [...new Set(out)];
}

export interface PmSide { long?: boolean; description?: string; team?: { name?: string; abbreviation?: string } | null }
export interface PmMarket {
  slug?: string;
  marketType?: string;
  sportsMarketType?: string;
  line?: number | string | null;
  bestBidQuote?: { value?: string | number } | null;
  bestAskQuote?: { value?: string | number } | null;
  feeCoefficient?: number | string | null;
  status?: string;
  active?: boolean;
  closed?: boolean;
  metadata?: { playerName?: string; teamId?: number } | null;
  marketSides?: PmSide[];
}
export interface PmEvent { slug?: string; startTime?: string; teams?: { id?: number; name?: string; abbreviation?: string }[]; markets?: PmMarket[] }

const hits = new Map<string, { at: number; ev: PmEvent }>();
const misses = new Map<string, number>();

async function getSlug(slug: string): Promise<PmEvent | null> {
  const now = Date.now();
  const h = hits.get(slug);
  if (h && now - h.at < TTL_MS) return h.ev;
  const m = misses.get(slug);
  if (m && now - m < MISS_TTL_MS) return null;
  try {
    const r = await fetch(`${BASE}/v1/events/slug/${encodeURIComponent(slug)}`, { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS), headers: { accept: "application/json" } });
    if (r.status === 404) {
      misses.set(slug, now);
      return null;
    }
    if (!r.ok) return h?.ev ?? null;
    const d = (await r.json()) as { event?: PmEvent } & PmEvent;
    const ev = d.event ?? d;
    hits.set(slug, { at: now, ev });
    return ev;
  } catch {
    return h?.ev ?? null; // keep the last copy on a timeout rather than blanking the page
  }
}

const found = new Map<string, string>(); // game → slug that worked

export async function fetchEvent(league: League, gameId: string, away: string, home: string, date: string): Promise<PmEvent | null> {
  const known = found.get(`${league}:${gameId}`);
  if (known) {
    const ev = await getSlug(known);
    if (ev) return ev;
  }
  for (const slug of candidateSlugs(league, away, home, date)) {
    const ev = await getSlug(slug);
    if (ev) {
      found.set(`${league}:${gameId}`, slug);
      return ev;
    }
  }
  return null;
}

/** Several games at once, a few requests at a time. */
async function fetchMany<T extends { id: string }>(items: T[], fn: (x: T) => Promise<PmEvent | null>, width = 4): Promise<Map<string, PmEvent>> {
  const out = new Map<string, PmEvent>();
  for (let i = 0; i < items.length; i += width) {
    const part = items.slice(i, i + width);
    const evs = await Promise.all(part.map(fn));
    part.forEach((x, j) => evs[j] && out.set(x.id, evs[j]!));
  }
  return out;
}

// ------------------------------------------------------------------ parsing
const num = (v: unknown): number | null => {
  const x = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(x) ? x : null;
};
const price = (v: unknown): number | null => {
  const x = num(v);
  return x === null || x <= 0 || x >= 1 ? null : x;
};

export const MARKET_TYPES: Record<string, string> = {
  football_player_passing_yards: "passing_yards",
  football_player_passing_attempts: "passing_attempts",
  football_player_passing_completions: "passing_completions",
  football_player_passing_touchdowns: "passing_tds",
  football_player_interceptions_thrown: "interceptions",
  football_player_rushing_yards: "rushing_yards",
  football_player_rushing_attempts: "rushing_attempts",
  football_player_receiving_yards: "receiving_yards",
  football_player_receptions: "receptions",
  football_player_scrimmage_yards: "rush_rec_yards",
  football_player_touchdowns: "anytime_td",
  football_player_longest_reception: "longest_reception",
  football_player_fantasy_points_ppr: "fantasy_points",
  basketball_player_points: "points",
  basketball_player_rebounds: "rebounds",
  basketball_player_assists: "assists",
  basketball_player_points_rebounds_assists: "pra",
  basketball_player_threes: "threes",
  basketball_player_steals: "steals",
  basketball_player_blocks: "blocks",
};

export interface LiveQuote { bid: number | null; ask: number | null; fee: number | null; status: string; slug: string | null }
export interface LiveProp extends LiveQuote { market: string; line: number; player: string }

function quote(m: PmMarket): LiveQuote {
  const closed = m.active === false || Boolean(m.closed);
  return {
    bid: price(m.bestBidQuote?.value),
    ask: price(m.bestAskQuote?.value),
    fee: num(m.feeCoefficient),
    status: closed ? "closed" : (m.status ?? "").replace("MARKET_STATUS_", "").toLowerCase() || "open",
    slug: m.slug ?? null,
  };
}

export function parseProps(ev: PmEvent): LiveProp[] {
  const out: LiveProp[] = [];
  for (const m of ev.markets ?? []) {
    const market = MARKET_TYPES[m.sportsMarketType ?? ""];
    const line = num(m.line);
    const player = m.metadata?.playerName;
    if (!market || line === null || !player) continue;
    out.push({ market, line, player, ...quote(m) });
  }
  return out;
}

const fullGame = (key: string, smt: string) =>
  key === "spread" ? smt.endsWith("full_game_spread") : key === "total" ? smt.endsWith("full_game_total") && !smt.includes("team_points") : smt === "moneyline" || smt.endsWith("full_game_winner");
const PM_TYPES: Record<string, string> = { spreads: "spread", totals: "total", moneyline: "winner" };

export interface LiveGameLines {
  /** Main spread as the home team's line (negative = home favored), from the contract priced closest to 50¢. */
  spread: { home: number; mid: number } | null;
  total: { line: number; mid: number } | null;
  homeWin: number | null;
}

type TeamRef = { abbr: string; name: string };
function sideTeam(league: League, s: PmSide, home: TeamRef, away: TeamRef): "home" | "away" | null {
  const ab = (s.team?.abbreviation ?? "").toLowerCase();
  const nm = (s.team?.name ?? "").toLowerCase();
  for (const [k, t] of [["home", home], ["away", away]] as const) {
    if ((ab && slugCodes(league, t.abbr).includes(ab)) || (nm && nm === t.name.toLowerCase())) return k;
  }
  return null;
}

export function parseGame(league: League, ev: PmEvent, home: TeamRef, away: TeamRef): LiveGameLines {
  const spreads: { home: number; mid: number }[] = [];
  const totals: { line: number; mid: number }[] = [];
  let homeWin: number | null = null;
  for (const m of ev.markets ?? []) {
    const key = PM_TYPES[m.marketType ?? ""];
    if (!key || !fullGame(key, m.sportsMarketType ?? "")) continue;
    const long = (m.marketSides ?? []).find((s) => s.long);
    if (!long) continue;
    const q = quote(m);
    if (q.bid === null || q.ask === null || q.bid > q.ask || q.status !== "open") continue;
    const mid = (q.bid + q.ask) / 2;
    const line = num(m.line);
    if (key === "total") {
      if (line !== null && (long.description ?? "").toLowerCase().startsWith("over")) totals.push({ line, mid });
      continue;
    }
    const side = sideTeam(league, long, home, away);
    if (!side) continue;
    if (key === "winner") homeWin = side === "home" ? mid : 1 - mid;
    else if (line !== null) spreads.push({ home: side === "home" ? line : -line, mid });
  }
  const main = <T extends { mid: number }>(xs: T[]) => (xs.length ? [...xs].sort((a, b) => Math.abs(a.mid - 0.5) - Math.abs(b.mid - 0.5))[0] : null);
  return { spread: main(spreads), total: main(totals), homeWin };
}

// ------------------------------------------------------------------ props board
export const normName = (s: string) =>
  s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z ]/g, "").replace(/\b(jr|sr|ii|iii|iv|v)\b/g, "").replace(/\s+/g, " ").trim();

/** Calibrated P(stat >= k) from the board's grid (linear between 5-yard points). */
export function gridProb(grid: { k0: number; step: number; p: number[] } | undefined, k: number): number | null {
  if (!grid || !grid.p.length) return null;
  const x = (k - grid.k0) / grid.step;
  if (x <= 0) return grid.p[0];
  if (x >= grid.p.length - 1) return grid.p[grid.p.length - 1];
  const i = Math.floor(x), f = x - i;
  return grid.p[i] * (1 - f) + grid.p[i + 1] * f;
}

const fee = (theta: number | null, x: number | null) => (theta && x !== null ? theta * x * (1 - x) : 0);
const r4 = (x: number) => Math.round(x * 1e4) / 1e4;

export function quoteView(q: LiveQuote, p: number, capturedAt: string, started: boolean): EngineQuoteView {
  const noAsk = q.bid !== null ? 1 - q.bid : null;
  const flags: string[] = [];
  if (started) flags.push("game started");
  if (q.status !== "open" && q.status !== "active") flags.push(`status ${q.status}`);
  if (q.bid === null || q.ask === null) flags.push("one-sided");
  else if (q.bid > q.ask + 1e-9) flags.push("crossed book");
  else if (q.ask - q.bid > MAX_SPREAD + 1e-9) flags.push("wide spread");
  const fy = fee(q.fee, q.ask), fn = fee(q.fee, noAsk);
  return {
    provider: PROVIDER,
    yes_bid: q.bid,
    yes_ask: q.ask,
    no_ask: noAsk,
    mid: q.bid !== null && q.ask !== null ? r4((q.bid + q.ask) / 2) : null,
    spread: q.bid !== null && q.ask !== null ? r4(q.ask - q.bid) : null,
    ask_size: null,
    fee_yes: q.ask !== null ? r4(fy) : null,
    fee_no: noAsk !== null ? r4(fn) : null,
    ev_yes: q.ask !== null ? r4(p - q.ask - fy) : null,
    ev_no: noAsk !== null ? r4(1 - p - noAsk - fn) : null,
    captured_at: capturedAt,
    usable: flags.length === 0,
    flags,
  };
}

/** Best price per side among usable quotes (same rule as the Python engine). Sizes aren't in the listing, so an edge is a lean at most. */
export function bestOf(views: EngineQuoteView[]): EngineThreshold["best"] {
  const ok = views.filter((v) => v.usable);
  const pick = (side: "yes" | "no"): EngineBestSide | null => {
    const xs = ok.filter((v) => (side === "yes" ? v.yes_ask : v.no_ask) !== null);
    if (!xs.length) return null;
    const cost = (v: EngineQuoteView) => (side === "yes" ? v.yes_ask! + (v.fee_yes ?? 0) : v.no_ask! + (v.fee_no ?? 0));
    const v = xs.reduce((a, b) => (cost(b) < cost(a) ? b : a));
    return { provider: v.provider, price: side === "yes" ? v.yes_ask! : v.no_ask!, fee: side === "yes" ? v.fee_yes : v.fee_no, ev: side === "yes" ? v.ev_yes : v.ev_no };
  };
  const yes = pick("yes"), no = pick("no");
  const cands = ([["yes", yes], ["no", no]] as const).filter(([, b]) => b && b.ev !== null && b.ev >= MIN_EV);
  const edge = cands.length ? cands.reduce((a, b) => (b[1]!.ev! > a[1]!.ev! ? b : a))[0] : null;
  return { yes, no, edge };
}

export interface LiveInfo { provider: string; fetchedAt: string; games: number; found: number; matched: number }

/**
 * A copy of the board with live Polymarket US quotes merged into the listed games. Lines the board
 * doesn't carry are added, priced from the market's probability grid. Other games are left as they are.
 */
export async function withLivePolymarket(league: League, board: EnginePropsBoard, gameIds: Set<string>, now = new Date()): Promise<{ board: EnginePropsBoard; info: LiveInfo }> {
  const capturedAt = now.toISOString();
  const targets = board.games.filter((g) => gameIds.has(g.game_id));
  const events = await fetchMany(targets.map((g) => ({ id: g.game_id, g })), ({ g }) => fetchEvent(league, g.game_id, g.away.abbr, g.home.abbr, g.game_date));
  let matched = 0;
  const games = board.games.map((g) => {
    const ev = events.get(g.game_id);
    if (!ev) return g;
    const started = Boolean(g.start_time && Date.parse(g.start_time) <= now.getTime());
    const byName = new Map(g.players.map((p) => [normName(p.name), p]));
    const extra = new Map<string, LiveProp[]>();
    for (const q of parseProps(ev)) {
      const p = byName.get(normName(q.player));
      if (!p || !p.markets[q.market]) continue;
      const k = `${p.player_id}|${q.market}`;
      extra.set(k, [...(extra.get(k) ?? []), q]);
    }
    if (!extra.size) return g;
    const players = g.players.map((p) => {
      let touched = false;
      const markets = { ...p.markets };
      for (const [mk, m] of Object.entries(p.markets)) {
        const qs = extra.get(`${p.player_id}|${mk}`);
        if (!qs) continue;
        touched = true;
        const th = m.thresholds.map((t) => ({ ...t, quotes: [...t.quotes] }));
        for (const q of qs) {
          let t = th.find((x) => x.op === ">=" && x.threshold === q.line && !x.variant);
          if (!t) {
            const prob = gridProb(m.grid, q.line);
            if (prob === null) continue;
            t = { op: ">=", threshold: q.line, variant: null, model_prob: r4(prob), model_prob_raw: r4(prob), quotes: [], best: null, edge_grade: { grade: null, reasons: [] } };
            th.push(t);
          }
          t.quotes = t.quotes.filter((v) => v.provider !== PROVIDER).concat(quoteView(q, t.model_prob, capturedAt, started));
          t.best = bestOf(t.quotes);
          t.edge_grade = t.best?.edge
            ? { grade: "lean", reasons: ["live owner view: contract sizes at that price aren't in Polymarket's listing, so this can't be graded strong"] }
            : { grade: null, reasons: [] };
          matched++;
        }
        th.sort((a, b) => a.threshold - b.threshold || a.op.localeCompare(b.op));
        markets[mk] = { ...m, thresholds: th };
      }
      return touched ? { ...p, markets } : p;
    });
    return { ...g, players };
  });
  return {
    board: { ...board, games },
    info: { provider: PROVIDER, fetchedAt: capturedAt, games: targets.length, found: events.size, matched },
  };
}

/** Main live game lines for a set of games (owner view only; the caller checks ownerLiveMarkets()). */
export async function liveGameLines(league: League, games: { id: string; gameDate: string; home: TeamRef; away: TeamRef }[]): Promise<Map<string, LiveGameLines>> {
  const events = await fetchMany(games, (g) => fetchEvent(league, g.id, g.away.abbr, g.home.abbr, g.gameDate));
  const out = new Map<string, LiveGameLines>();
  for (const g of games) {
    const ev = events.get(g.id);
    if (ev) out.set(g.id, parseGame(league, ev, g.home, g.away));
  }
  return out;
}
