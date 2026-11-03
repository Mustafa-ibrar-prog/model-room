import "server-only";
import { canAccess, gate } from "@/lib/entitlements";
import { loadPropsBoard } from "@/server/engine/board";
import type { Gate, League, TierId } from "@/types/domain";
import type { EnginePropPlayer, EnginePropsBoard, PropBacktestSummary, PropLineView } from "@/types/props";
import { lineView } from "./props";
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
  { key: "edge", label: "Biggest edge" },
  { key: "projection", label: "Projection" },
  { key: "probability", label: "Probability" },
  { key: "confidence", label: "Confidence" },
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

export interface ExplorerRow {
  id: string;
  gameId: string;
  matchup: string;
  name: string;
  team: string;
  opp: string;
  position: string;
  injuryStatus: string | null;
  mean: number;
  median: number;
  sd: number;
  range80: [number, number];
  support: "ok" | "limited" | "insufficient";
  supportNote: string;
  headline: PropLineView | null;
  lines: PropLineView[];
  bestEdge: number | null;
  strong: boolean;
  inputs: Gate<Record<string, unknown>>;
  /** Last games before the run for this stat, newest first. */
  recent: { date: string; opp: string; value: number | null }[];
}

export interface ContractDetail {
  row: ExplorerRow;
  line: PropLineView;
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
      /** Set when live Polymarket US prices were merged in (owner view on the test site only). */
      live: LiveInfo | null;
    };

const SUPPORT_RANK = { ok: 0, limited: 1, insufficient: 2 } as const;

function headline(lines: PropLineView[]): PropLineView | null {
  if (!lines.length) return null;
  // With prices: the market's main line (priced closest to 50¢). Without: the model's coin-flip line.
  const priced = lines.filter((l) => l.market?.mid != null);
  if (priced.length) return [...priced].sort((a, b) => Math.abs(a.market!.mid! - 0.5) - Math.abs(b.market!.mid! - 0.5))[0];
  return [...lines].sort((a, b) => Math.abs(a.modelProb - 0.5) - Math.abs(b.modelProb - 0.5))[0];
}

function rowFor(p: EnginePropPlayer, cat: Category, tier: TierId, matchup: string): ExplorerRow | null {
  const m = p.markets[cat.key];
  if (!m) return null;
  if (cat.positions && !cat.positions.includes(p.position)) return null;
  if (cat.minMean !== undefined && m.mean < cat.minMean) return null;
  const lines = m.thresholds.map(lineView);
  const edges = lines.filter((l) => l.edge).map((l) => l.edge!.ev);
  const rv = p.recent?.values?.[cat.key] ?? [];
  return {
    id: p.player_id,
    gameId: p.game_id,
    matchup,
    name: p.name,
    team: p.team,
    opp: p.opp,
    position: p.position,
    injuryStatus: p.injury_status,
    mean: m.mean,
    median: m.median,
    sd: m.sd,
    range80: m.range_80,
    support: m.support,
    supportNote: m.support_note,
    headline: headline(lines),
    lines,
    bestEdge: edges.length ? Math.max(...edges) : null,
    strong: lines.some((l) => l.edge?.grade === "strong"),
    inputs: gate(tier, "props.advanced", p.inputs as Record<string, unknown>),
    recent: (p.recent?.games ?? []).map((g, i) => ({ date: g.date, opp: g.opp, value: rv[i] ?? null })),
  };
}

function sortRows(rows: ExplorerRow[], sort: SortKey): ExplorerRow[] {
  const by: Record<SortKey, (a: ExplorerRow, b: ExplorerRow) => number> = {
    edge: (a, b) => (b.bestEdge ?? -1) - (a.bestEdge ?? -1) || b.median - a.median,
    projection: (a, b) => b.median - a.median,
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
    let list = pool.flatMap((g) => g.players.map((p) => rowFor(p, category, tier, `${g.away.abbr} @ ${g.home.abbr}`))).filter((r): r is ExplorerRow => r !== null);
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
      const row = src && g ? rowFor(src, category, tier, `${g.away.abbr} @ ${g.home.abbr}`) : null;
      const line = row?.lines.find((l) => lineKey(row.id, l) === query.line) ?? null;
      detail = row && line ? { row, line, key: query.line, marketStats: b.performance.backtest?.by_market?.[category.key] ?? null } : null;
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
  };
}
