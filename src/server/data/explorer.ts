import "server-only";
import { canAccess, gate } from "@/lib/entitlements";
import { loadPropsBoard } from "@/server/engine/board";
import type { Gate, League, TierId } from "@/types/domain";
import type { EnginePropPlayer, EnginePropsBoard, PropLineView } from "@/types/props";
import { lineView } from "./props";

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
  only?: string; // "edges" | "strong" | "ok"
}

export interface ExplorerRow {
  id: string;
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
    };

const SUPPORT_RANK = { ok: 0, limited: 1, insufficient: 2 } as const;

function headline(lines: PropLineView[]): PropLineView | null {
  if (!lines.length) return null;
  const priced = lines.filter((l) => l.market);
  const pool = priced.length ? priced : lines;
  return [...pool].sort((a, b) => Math.abs(a.modelProb - 0.5) - Math.abs(b.modelProb - 0.5))[0];
}

function rowFor(p: EnginePropPlayer, cat: Category, tier: TierId): ExplorerRow | null {
  const m = p.markets[cat.key];
  if (!m) return null;
  if (cat.positions && !cat.positions.includes(p.position)) return null;
  if (cat.minMean !== undefined && m.mean < cat.minMean) return null;
  const lines = m.thresholds.map(lineView);
  const edges = lines.filter((l) => l.edge).map((l) => l.edge!.ev);
  return {
    id: p.player_id,
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
  const b = res.board;
  const games: ExplorerGame[] = b.games.map((g) => ({
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
  const selected = b.games.find((g) => g.game_id === query.game) ?? b.games.find((g) => !g.start_time || Date.parse(g.start_time) > now.getTime()) ?? b.games[0];
  const game = selected ? games.find((g) => g.id === selected.game_id) ?? null : null;
  let rows: Gate<ExplorerRow[]>;
  let total = 0;
  if (!canAccess(tier, "props.projections")) {
    rows = gate(tier, "props.projections", []);
  } else {
    let list = (selected?.players ?? []).map((p) => rowFor(p, category, tier)).filter((r): r is ExplorerRow => r !== null);
    total = list.length;
    const q = (query.q ?? "").trim().toLowerCase();
    if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
    if (query.team && selected && [selected.home.abbr, selected.away.abbr].includes(query.team)) list = list.filter((r) => r.team === query.team);
    if (query.only === "edges") list = list.filter((r) => r.bestEdge !== null);
    if (query.only === "strong") list = list.filter((r) => r.strong);
    if (query.only === "ok") list = list.filter((r) => r.support === "ok");
    rows = sortRows(list, sort);
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
  };
}
