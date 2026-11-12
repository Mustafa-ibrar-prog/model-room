import "server-only";
import { canAccess, gate } from "@/lib/entitlements";
import { loadLiveInjuries, loadPropsBoard, type LiveInjuries } from "@/server/engine/board";
import { preferredOutcome, type Ladder, type LineProbs, type Preferred } from "@/lib/propOutcome";
import type { Gate, League, TierId } from "@/types/domain";
import type { EnginePropPlayer, EnginePropsBoard, PropBacktestSummary, PropLineView } from "@/types/props";
import { lineView, scalarInputs } from "./props";
import { ownerLiveMarkets, withLivePolymarket, type LiveInfo } from "@/server/markets/polymarketLive";

/**
 * Props explorer: sport → game → category → the players that matter for that category.
 * Filtering and sorting happen here, on the server, so a page only carries the rows it shows and a
 * plan without player props receives no player data at all.
 */

export interface Category {
  key: string;
  label: string;
  positions: string[] | null; // null = every position
  minMean?: number;           // hide players whose projection is negligible for this stat
}

export const CATEGORIES: Record<League, Category[]> = {
  nfl: [
    { key: "passing_yards", label: "Passing yards", positions: ["QB"] },
    { key: "passing_tds", label: "Passing TDs", positions: ["QB"] },
    { key: "passing_attempts", label: "Pass attempts", positions: ["QB"] },
    { key: "passing_completions", label: "Completions", positions: ["QB"] },
    { key: "interceptions", label: "Interceptions", positions: ["QB"] },
    { key: "rushing_yards", label: "Rushing yards", positions: ["RB", "QB", "WR"], minMean: 8 },
    { key: "rushing_attempts", label: "Rush attempts", positions: ["RB", "QB"], minMean: 3 },
    { key: "receiving_yards", label: "Receiving yards", positions: ["WR", "TE", "RB"], minMean: 8 },
    { key: "receptions", label: "Receptions", positions: ["WR", "TE", "RB"], minMean: 1 },
    { key: "longest_reception", label: "Longest reception", positions: ["WR", "TE", "RB"], minMean: 5 },
    { key: "rush_rec_yards", label: "Rush + rec yards", positions: ["RB", "WR", "TE"], minMean: 15 },
    { key: "anytime_td", label: "Anytime TD", positions: ["RB", "WR", "TE", "QB"], minMean: 0.1 },
    { key: "fantasy_points", label: "Fantasy points", positions: null, minMean: 4 },
  ],
  nba: [
    { key: "points", label: "Points", positions: null },
    { key: "rebounds", label: "Rebounds", positions: null },
    { key: "assists", label: "Assists", positions: null },
    { key: "pra", label: "Pts + reb + ast", positions: null },
    { key: "threes", label: "Threes", positions: null, minMean: 0.3 },
    { key: "steals", label: "Steals", positions: null },
    { key: "blocks", label: "Blocks", positions: null },
  ],
};

export const SORTS = [
  { key: "edge", label: "Model-implied value" },
  { key: "projection", label: "Projection" },
  { key: "probability", label: "Probability" },
  { key: "confidence", label: "Data history" },
  { key: "player", label: "Player" },
] as const;
export type SortKey = (typeof SORTS)[number]["key"];

export interface ExplorerQuery {
  game?: string;
  cat?: string;
  q?: string;
  sort?: string;
  team?: string;
  only?: string; // "edges" | "strong" | "ok" | "priced"
  line?: string; // selected contract: <playerId>~<op><threshold>[~<variant>]
  date?: string; // today or a coming day: only that day's games
}

/** Stable key for one contract (player + threshold), used in the URL and for favorites. */
export function lineKey(playerId: string, l: { op: string; threshold: number; variant: string | null }): string {
  return `${playerId}~${l.op === ">" ? "gt" : "ge"}${l.threshold}${l.variant ? `~${l.variant}` : ""}`;
}

export interface PlayerInjury {
  status: string | null;
  rawStatus: string | null;
  source: string | null;
  confirmed: boolean;
  reportTime: string | null;
  notes: string[];
  conflict: string | null;
  lateScratch: boolean;
  startingQb: string | null;
  starterConfirmed: boolean | null;
}

function playerInjury(inputs: Record<string, unknown>): PlayerInjury | null {
  const a = (inputs.availability ?? null) as Record<string, unknown> | null;
  const qb = (inputs.starting_qb as string | undefined) ?? null;
  if (!a && !qb) return null;
  return {
    status: (a?.status as string) ?? null,
    rawStatus: (a?.raw_status as string) ?? null,
    source: (a?.source as string) ?? null,
    confirmed: Boolean(a?.confirmed),
    reportTime: (a?.report_time as string) ?? null,
    notes: ((a?.notes as string[]) ?? []).filter(Boolean),
    conflict: (a?.conflict as string) ?? null,
    lateScratch: Boolean(a?.late_scratch),
    startingQb: qb,
    starterConfirmed: (a?.starter_confirmed as boolean | null | undefined) ?? null,
  };
}

/** Category key → the stat the NBA engine records contributions under (NFL records them by market key). */
const NBA_STAT: Record<string, string> = { points: "pts", rebounds: "reb", assists: "ast", pra: "pra", threes: "fg3m", steals: "stl", blocks: "blk" };

/** One recorded step of the model's own projection (P3): its change in the average, in the model's fixed order. */
export interface ContributionView {
  /** null: the engine didn't isolate this market's adjustments (or the board predates the recording). */
  steps: { key: string; value: number }[] | null;
  final: number | null;
  reason: string | null;
  /** NBA: usual / after-fill / projected minutes. */
  minutes: { usual: number; after_fill: number; projected: number } | null;
}

function contributionView(league: League, cat: string, inputs: Record<string, unknown>): ContributionView {
  const c = inputs?.contributions as { order?: string[]; stats?: Record<string, Record<string, number> | null>; unavailable?: string; minutes?: ContributionView["minutes"] } | undefined;
  if (!c || !c.stats) return { steps: null, final: null, reason: "not recorded for this projection", minutes: null };
  const ch = c.stats[league === "nba" ? NBA_STAT[cat] ?? cat : cat];
  if (!ch) return { steps: null, final: null, reason: c.unavailable ?? "this market's adjustments are not isolated by the model", minutes: c.minutes ?? null };
  const steps = (c.order ?? Object.keys(ch)).filter((k) => k in ch && k !== "final").map((k) => ({ key: k, value: ch[k] }));
  return { steps, final: ch.final ?? null, reason: null, minutes: c.minutes ?? null };
}

/** Over / Push / Under at a quoted exchange contract: its published model probability (binary contracts can't push). */
export function contractProbs(l: PropLineView): LineProbs {
  return { over: l.modelProb, under: 1 - l.modelProb, push: 0, outsideRange: false, line: l.op === ">=" ? l.threshold - 0.5 : l.threshold };
}

/** When the line was observed: the shown quote's capture time, else the latest quote's. */
export function observedAt(l: PropLineView): string | null {
  if (l.market) return l.market.capturedAt;
  const qs = [...l.quotes].sort((a, b) => b.capturedAt.localeCompare(a.capturedAt));
  return qs[0]?.capturedAt ?? null;
}

export interface ExplorerRow {
  id: string;
  gameId: string;
  matchup: string;
  name: string;
  team: string;
  opp: string;
  position: string;
  injuryStatus: string | null;
  /** Injury feed for this player (test site): status with source / time; null when no feed or no entry. */
  injury: PlayerInjury | null;
  /** Teammates ruled out for this game (the absences behind his projection). */
  teammatesOut: { name: string; status: string; source: string; position?: string | null }[];
  changes: EnginePropPlayer["changes"] | null;
  mean: number;
  median: number;
  sd: number;
  range80: [number, number];
  support: "ok" | "limited" | "insufficient";
  supportNote: string;
  /** The market's main line for this player and stat (a quoted contract); null when no market lists one. */
  headline: PropLineView | null;
  lines: PropLineView[];
  /** Model thresholds with no market quote: the model's own ladder, never presented as a market line. */
  ladder: PropLineView[];
  /** Calibrated P(stat >= k) ladder published with the board (null on boards that predate it). */
  grid: Ladder | null;
  /** Model Room probabilities at the market line, and the outcome they prefer (none without a market line). */
  atLine: LineProbs | null;
  preferred: Preferred | { kind: "none"; reason: "stale_line" };
  /** The model's own record of how it reached the average (Pro, like the other model inputs). */
  contributions: Gate<ContributionView>;
  /** NBA: players the active model treats as out (missed his team's recent games), from the projection's own inputs. */
  modelAbsences: string | null;
  bestEdge: number | null;
  strong: boolean;
  inputs: Gate<Record<string, unknown>>;
  /** Last games before the run for this stat, newest first. */
  recent: { date: string; opp: string; value: number | null }[];
}

export interface ContractDetail {
  row: ExplorerRow;
  /** The selected contract or model threshold; null = the player's card with no line picked (no market line). */
  line: PropLineView | null;
  key: string;
  marketStats: PropBacktestSummary["by_market"][string] | null;
}

export interface ExplorerGame {
  id: string;
  startTime: string | null;
  gameDate: string;
  home: { abbr: string; name: string };
  away: { abbr: string; name: string };
  status: "upcoming" | "started";
}

export type Explorer =
  | { ok: false; reason: string }
  | {
      ok: true;
      league: League;
      generatedAt: string;
      /** Request time (ms), for quote ages. */
      now: number;
      model: { version: string; status: string };
      games: ExplorerGame[];
      game: ExplorerGame | null;
      categories: Category[];
      category: Category;
      sort: SortKey;
      query: ExplorerQuery;
      providers: EnginePropsBoard["data"]["markets"];
      rules: EnginePropsBoard["data"]["comparison_rules"];
      backtest: EnginePropsBoard["performance"]["backtest"];
      rows: Gate<ExplorerRow[]>;
      totalPlayers: number;
      /** Searching across every game of the sport (q given, no game picked). */
      searchAll: boolean;
      detail: Gate<ContractDetail | null>;
      /** Injury feed rows for the selected game's two teams (test site), and when the feed was built. */
      injuries: { team: string; rows: { player: string; position: string | null; status: string; source: string; reportTime: string | null }[] }[] | null;
      injuryFeedAt: string | null;
      /** Set when live Polymarket US prices were merged in (owner view on the test site only). */
      live: LiveInfo | null;
    };

const SUPPORT_RANK = { ok: 0, limited: 1, insufficient: 2 } as const;

/** Market midpoint for a line: the usable quote's, else any two-sided quote's (wide or thin, for reference only). */
export function marketMid(l: PropLineView): number | null {
  return l.market?.mid ?? l.quotes.find((q) => q.mid != null && !q.flags.includes("crossed book"))?.mid ?? null;
}

/** The market's main line: the quoted contract priced closest to 50¢. Without a market quote there is no headline: the
 * model's own coin-flip threshold is never presented as a market line. */
function headline(lines: PropLineView[]): PropLineView | null {
  const priced = lines.filter((l) => marketMid(l) != null);
  if (priced.length) return [...priced].sort((a, b) => Math.abs(marketMid(a)! - 0.5) - Math.abs(marketMid(b)! - 0.5))[0];
  return null;
}

/** Every quote on the line is stale (older than the comparison window): the line may have moved. */
export const staleLine = (l: PropLineView) => !l.market && l.quotes.length > 0 && l.quotes.every((q) => q.flags.includes("stale"));

function rowFor(p: EnginePropPlayer, cat: Category, tier: TierId, matchup: string, league: League = "nfl"): ExplorerRow | null {
  const m = p.markets[cat.key];
  if (!m) return null;
  if (cat.positions && !cat.positions.includes(p.position)) return null;
  if (cat.minMean !== undefined && m.mean < cat.minMean) return null;
  const lines = m.thresholds.map(lineView);
  const edges = lines.filter((l) => l.edge).map((l) => l.edge!.ev);
  const rv = p.recent?.values?.[cat.key] ?? [];
  const head = headline(lines);
  const atLine = head ? contractProbs(head) : null;
  const preferred = head && staleLine(head) ? ({ kind: "none", reason: "stale_line" } as const) : preferredOutcome(atLine, { support: m.support, mean: m.mean });
  return {
    id: p.player_id,
    gameId: p.game_id,
    matchup,
    name: p.name,
    team: p.team,
    opp: p.opp,
    position: p.position,
    injuryStatus: p.injury_status,
    injury: playerInjury(p.inputs ?? {}),
    teammatesOut: ((p.inputs?.teammates_out_detail as ExplorerRow["teammatesOut"] | undefined) ?? []).slice(0, 8),
    changes: p.changes ?? null,
    mean: m.mean,
    median: m.median,
    sd: m.sd,
    range80: m.range_80,
    support: m.support,
    supportNote: m.support_note,
    headline: head,
    lines,
    ladder: lines.filter((l) => !l.quotes.length),
    grid: m.grid ?? null,
    atLine,
    preferred,
    contributions: gate(tier, "props.advanced", contributionView(league, cat.key, p.inputs ?? {})),
    modelAbsences: league === "nba" ? ((p.inputs?.teammates_out as string | null | undefined) ?? null) : null,
    bestEdge: edges.length ? Math.max(...edges) : null,
    strong: lines.some((l) => l.edge?.grade === "strong"),
    inputs: gate(tier, "props.advanced", scalarInputs(p.inputs) as Record<string, unknown>),
    recent: (p.recent?.games ?? []).map((g, i) => ({ date: g.date, opp: g.opp, value: rv[i] ?? null })),
  };
}

function sortRows(rows: ExplorerRow[], sort: SortKey): ExplorerRow[] {
  const by: Record<SortKey, (a: ExplorerRow, b: ExplorerRow) => number> = {
    edge: (a, b) => (b.bestEdge ?? -1) - (a.bestEdge ?? -1) || b.mean - a.mean,
    projection: (a, b) => b.mean - a.mean,
    probability: (a, b) => (b.headline?.modelProb ?? 0) - (a.headline?.modelProb ?? 0),
    confidence: (a, b) => SUPPORT_RANK[a.support] - SUPPORT_RANK[b.support] || a.sd / Math.max(a.mean, 0.5) - b.sd / Math.max(b.mean, 0.5),
    player: (a, b) => a.name.localeCompare(b.name),
  };
  return [...rows].sort(by[sort]);
}

export async function getExplorer(league: League, tier: TierId, query: ExplorerQuery, at?: Date): Promise<Explorer> {
  const res = await loadPropsBoard(league); // reads at request time (connection()), so the clock below is per request
  if (!res.ok) return { ok: false, reason: res.reason };
  const now = at ?? new Date();
  let b = res.board;
  let live: LiveInfo | null = null;
  if (canAccess(tier, "props.projections") && (await ownerLiveMarkets())) {
    const day = query.date ? b.games.filter((g) => g.game_date === query.date) : b.games;
    const q0 = (query.q ?? "").trim();
    const pick = day.find((g) => g.game_id === query.game) ?? day.find((g) => !g.start_time || Date.parse(g.start_time) > now.getTime()) ?? day[0];
    const ids = new Set((q0 && !query.game ? day : pick ? [pick] : []).map((g) => g.game_id));
    ({ board: b, info: live } = await withLivePolymarket(league, b, ids, now));
  }
  const dayGames = query.date ? b.games.filter((g) => g.game_date === query.date) : b.games;
  const games: ExplorerGame[] = dayGames.map((g) => ({
    id: g.game_id,
    startTime: g.start_time,
    gameDate: g.game_date,
    home: g.home,
    away: g.away,
    status: g.start_time && Date.parse(g.start_time) <= now.getTime() ? "started" : "upcoming",
  }));
  const cats = CATEGORIES[league];
  const category = cats.find((c) => c.key === query.cat) ?? cats[0];
  const sort = (SORTS.find((s) => s.key === query.sort)?.key ?? "projection") as SortKey;
  const selected = dayGames.find((g) => g.game_id === query.game) ?? dayGames.find((g) => !g.start_time || Date.parse(g.start_time) > now.getTime()) ?? dayGames[0];
  const game = selected ? games.find((g) => g.id === selected.game_id) ?? null : null;
  let rows: Gate<ExplorerRow[]>;
  let total = 0;
  const q = (query.q ?? "").trim().toLowerCase();
  const searchAll = Boolean(q) && !query.game;
  let detail: Gate<ContractDetail | null> = null;
  if (!canAccess(tier, "props.projections")) {
    rows = gate(tier, "props.projections", []);
    detail = query.line ? gate(tier, "props.projections", null) : null;
  } else {
    const pool = searchAll ? dayGames : selected ? [selected] : [];
    let list = pool.flatMap((g) => g.players.map((p) => rowFor(p, category, tier, `${g.away.abbr} @ ${g.home.abbr}`, league))).filter((r): r is ExplorerRow => r !== null);
    total = list.length;
    if (q) list = list.filter((r) => r.name.toLowerCase().includes(q) || r.team.toLowerCase() === q || r.matchup.toLowerCase().includes(q));
    if (query.team && selected && !searchAll && [selected.home.abbr, selected.away.abbr].includes(query.team)) list = list.filter((r) => r.team === query.team);
    if (query.only === "edges") list = list.filter((r) => r.bestEdge !== null);
    if (query.only === "strong") list = list.filter((r) => r.strong);
    if (query.only === "ok") list = list.filter((r) => r.support === "ok");
    if (query.only === "priced") list = list.filter((r) => r.lines.some((l) => l.quotes.length));
    rows = sortRows(list, sort);
    if (query.line) {
      const pid = query.line.split("~")[0];
      const src = (selected?.players ?? []).concat(searchAll ? b.games.flatMap((g) => g.players) : []).find((p) => p.player_id === pid);
      const g = src ? b.games.find((x) => x.game_id === src.game_id) : undefined;
      const row = src && g ? rowFor(src, category, tier, `${g.away.abbr} @ ${g.home.abbr}`, league) : null;
      const line = row?.lines.find((l) => lineKey(row.id, l) === query.line) ?? null;
      const cardOnly = row && query.line === `${row.id}~card`;
      detail = row && (line || cardOnly) ? { row, line, key: query.line, marketStats: b.performance.backtest?.by_market?.[category.key] ?? null } : null;
    }
  }
  let injuries: Extract<Explorer, { ok: true }>["injuries"] = null;
  let injuryFeedAt: string | null = null;
  if (canAccess(tier, "props.projections") && selected && !searchAll) {
    const feed: LiveInjuries | null = await loadLiveInjuries(league);
    if (feed) {
      injuryFeedAt = feed.generated_at;
      const want = new Set(["out", "doubtful", "questionable"]);
      injuries = [selected.away.abbr, selected.home.abbr].map((t) => ({
        team: t,
        rows: feed.players
          .filter((r) => r.team === t && r.current && !r.stale && want.has(r.status))
          .map((r) => ({ player: r.player, position: r.position, status: r.status, source: r.source, reportTime: r.report_time })),
      }));
    }
  }
  return {
    ok: true,
    league,
    generatedAt: b.generated_at,
    now: now.getTime(),
    model: { version: b.model.version, status: b.model.status },
    games,
    game,
    categories: cats,
    category,
    sort,
    query,
    providers: b.data.markets,
    rules: b.data.comparison_rules,
    backtest: b.performance.backtest,
    rows,
    totalPlayers: total,
    searchAll,
    detail,
    live,
    injuries,
    injuryFeedAt,
  };
}
