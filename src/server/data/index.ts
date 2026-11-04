import "server-only";
import { FREE_EDGE_FINDER_LIMIT, canAccess, gate } from "@/lib/entitlements";
import { loadLiveInjuries, loadBoard } from "@/server/engine/board";
import type {
  Freshness,
  GameView,
  InjuryView,
  League,
  LeagueBoard,
  PerformanceView,
  RatingView,
  TierId,
} from "@/types/domain";
import type { EngineBoard, EngineGame } from "@/types/engine";

/**
 * Data Access Layer.
 *
 * The only path from engine output to a page or API route. Every premium
 * field passes through gate() here, so responses never contain values the
 * viewer's plan doesn't include. Missing data stays null; nothing is filled in.
 */

const UNAVAILABLE: Freshness = { status: "unavailable", reasons: [], resultsThrough: null, lastIngest: null, modelRunAt: null };

/** Projections older than this are shown as delayed, whatever they said when generated. */
const STALE_AFTER_HOURS = 30;

export function freshness(b: EngineBoard, now: Date = new Date()): Freshness {
  const ageHours = (now.getTime() - Date.parse(b.generated_at)) / 3_600_000;
  const stale = Number.isFinite(ageHours) && ageHours > STALE_AFTER_HOURS;
  return {
    status: stale ? "delayed" : b.data.freshness.status,
    reasons: stale ? [`Projections are ${Math.round(ageHours)} hours old`, ...b.data.freshness.reasons] : b.data.freshness.reasons,
    resultsThrough: b.data.freshness.results_through,
    lastIngest: b.data.freshness.last_ingest,
    modelRunAt: b.generated_at,
  };
}

export function toGameView(g: EngineGame, league: League, tier: TierId, edgeAllowed: boolean): GameView {
  const p = g.projection;
  const edgeFeature = edgeAllowed ? "games.edgeFinder.limited" : "games.edgeFinder.full";
  const e = g.edges;
  return {
    id: g.game_id,
    league,
    startTime: g.start_time,
    gameDate: g.game_date,
    status: g.status,
    week: g.week ?? null,
    neutral: g.neutral,
    home: { abbr: g.home.abbr, name: g.home.name },
    away: { abbr: g.away.abbr, name: g.away.name },
    modelSpread: p.spread,
    modelTotal: p.total,
    projectedMargin: p.margin,
    projectedScore: gate(tier, "games.projectedScores", { home: p.home_score, away: p.away_score }),
    winProbability: gate(tier, "games.projectedScores", { home: p.home_win_prob, away: p.away_win_prob }),
    ranges: gate(tier, "games.projectedScores", { margin: p.margin_range_80, total: p.total_range_80 }),
    market: g.market
      ? {
          spread: g.market.spread,
          total: g.market.total,
          homeMoneyline: g.market.home_ml,
          awayMoneyline: g.market.away_ml,
          books: g.market.books,
          capturedAt: g.market.captured_at,
          sources: g.market.sources,
        }
      : null,
    spreadEdge: gate(tier, edgeFeature, e?.spread ?? null),
    totalEdge: gate(tier, edgeFeature, e?.total ?? null),
    probabilityEdge: gate(
      tier,
      edgeFeature,
      e && e.home_prob_market !== null && e.home_prob_diff !== null
        ? { homeMarket: e.home_prob_market, homeDiff: e.home_prob_diff }
        : null,
    ),
    rest: {
      homeDays: g.rest.home_days,
      awayDays: g.rest.away_days,
      homeB2b: Boolean(g.rest.home_b2b),
      awayB2b: Boolean(g.rest.away_b2b),
    },
    injuryAdjustment: gate(tier, "injuries.adjustments", g.adjustments.injury_points),
    quarterbacks: g.quarterbacks ?? null,
    qbAdjustment: gate(tier, "injuries.adjustments", g.adjustments.qb_points ?? null),
    availability: g.availability ?? null,
    changes: g.changes ?? null,
    result: g.result
      ? { homeScore: g.result.home_score, awayScore: g.result.away_score, margin: g.result.margin, total: g.result.total }
      : null,
  };
}

function performance(b: EngineBoard): PerformanceView {
  const bt = b.performance.backtest;
  const base = bt?.baselines ?? {};
  const mc = bt?.market_comparison as { spread?: { market_mae?: number }; total?: { market_mae?: number } } | string | null | undefined;
  return {
    backtest: bt
      ? {
          modelVersion: bt.model_version,
          testSeasons: bt.test_seasons,
          games: bt.games,
          marginMae: bt.margin_mae,
          totalMae: bt.total_mae,
          totalBias: bt.total_bias,
          brier: bt.brier,
          winnerCorrect: bt.winner_correct,
          baselines: [
            { label: "Home edge only", marginMae: base.home_court_margin_mae ?? null, totalMae: base.home_court_total_mae ?? null },
            ...(base.season_to_date_margin_mae != null
              ? [{ label: "Season-to-date margin", marginMae: base.season_to_date_margin_mae, totalMae: null }]
              : []),
          ],
          marketMarginMae: typeof mc === "object" && mc ? (mc.spread?.market_mae ?? null) : null,
          marketTotalMae: typeof mc === "object" && mc ? (mc.total?.market_mae ?? null) : null,
          calibration: bt.calibration,
        }
      : null,
    seasonToDate: b.performance.season_to_date
      ? {
          games: b.performance.season_to_date.games,
          marginMae: b.performance.season_to_date.margin_mae,
          totalMae: b.performance.season_to_date.total_mae,
          winnerCorrect: b.performance.season_to_date.winner_correct,
          note: b.performance.season_to_date.note,
        }
      : null,
    ledger: {
      tracked: b.performance.ledger.tracked,
      graded: b.performance.ledger.graded,
      versions: Object.entries(b.performance.ledger.by_version ?? {}).map(([version, v]) => ({
        version,
        games: v.games,
        marginMae: v.margin_mae,
        totalMae: v.total_mae,
        winnerCorrect: v.winner_correct,
      })),
    },
  };
}

export async function getLeagueBoard(league: League, tier: TierId): Promise<LeagueBoard> {
  const res = await loadBoard(league);
  if (!res.ok) return { ok: false, league, reason: res.reason, freshness: UNAVAILABLE };
  const b = res.board;
  const fullEdges = canAccess(tier, "games.edgeFinder.full");
  // Free: edges on the first FREE_EDGE_FINDER_LIMIT upcoming games that have a market line.
  let freeEdgesLeft = FREE_EDGE_FINDER_LIMIT;
  const upcoming = b.upcoming.map((g) => {
    const allowed = fullEdges || (g.market !== null && freeEdgesLeft-- > 0);
    return toGameView(g, league, tier, allowed);
  });
  const recent = b.recent.map((g) => toGameView(g, league, tier, fullEdges));
  const pregame: Record<string, { margin: number; total: number; homeWinProb: number }> = {};
  for (const g of b.recent) {
    pregame[g.game_id] = { margin: g.projection.margin, total: g.projection.total, homeWinProb: g.projection.home_win_prob };
  }
  return {
    ok: true,
    league,
    seasonLabel: b.season_label,
    week: b.week ?? null,
    model: { version: b.model.version, status: b.model.status, fittedAt: b.model.fitted_at, uncertaintyMethod: b.model.uncertainty.method },
    freshness: freshness(b),
    sources: b.data.sources,
    market: b.data.market,
    injuries: { connected: b.data.injuries.connected, note: b.data.injuries.note },
    upcoming,
    recent,
    // Pre-game projections for finished games are historical model data (Pro).
    recentPregame: gate(tier, "history", pregame),
    performance: performance(b),
  };
}

export async function getRatings(
  league: League,
  tier: TierId,
): Promise<{ ok: true; seasonLabel: string; modelVersion: string; rows: RatingView[] } | { ok: false; reason: string }> {
  const res = await loadBoard(league);
  if (!res.ok) return { ok: false, reason: res.reason };
  return {
    ok: true,
    seasonLabel: res.board.season_label,
    modelVersion: res.board.model.version,
    rows: res.board.ratings.map((r) => ({
      rank: r.rank,
      team: { abbr: r.abbr, name: r.name },
      games: r.games_played,
      overall: r.overall,
      overallUnit: r.overall_unit,
      avgMargin: r.avg_margin,
      last10Margin: r.last10_margin,
      components: gate(
        tier,
        "ratings.advanced",
        r.components.map((c) => ({ key: c.key, label: c.label, value: c.value, unit: c.unit, higherIsBetter: c.higher_is_better })),
      ),
    })),
  };
}

export async function getInjuries(
  league: League,
  tier: TierId,
): Promise<{ ok: true; connected: boolean; note: string | null; rows: InjuryView[] } | { ok: false; reason: string }> {
  const res = await loadBoard(league);
  if (!res.ok) return { ok: false, reason: res.reason };
  const b = res.board;
  const live = await loadLiveInjuries(league);
  if (live) {
    // The combined injury feed: one current status per player, with its source and time.
    const impact = new Map((b.injuries ?? []).map((i) => [`${i.team}|${i.player}`, i]));
    const order: Record<string, number> = { out: 0, doubtful: 1, questionable: 2, probable: 3 };
    const ok = Object.entries(live.sources).filter(([, v]) => v.ok).map(([k]) => k);
    const failed = Object.entries(live.sources).filter(([, v]) => !v.ok).map(([k]) => k);
    return {
      ok: true,
      connected: true,
      note: `${ok.map((k) => ({ nba_official: "official NBA injury report", espn: "ESPN injury reports", nflverse: "NFL injury report via nflverse" })[k] ?? k).join(" + ")}, as of ${new Date(live.generated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short" })}${failed.length ? `. Unavailable this refresh: ${failed.join(", ")}` : ""}${live.conflicts ? `. ${live.conflicts} conflicting reports (official designation used)` : ""}.`,
      rows: live.players
        .filter((p) => p.current && p.status in order)
        .sort((x, y) => order[x.status] - order[y.status] || x.team.localeCompare(y.team))
        .map((p) => {
          const i = impact.get(`${p.team}|${p.player}`);
          return {
            team: p.team,
            player: p.player,
            position: p.position,
            status: p.raw_status && p.raw_status.toLowerCase() !== p.status ? `${p.status[0].toUpperCase()}${p.status.slice(1)}` : (p.raw_status ?? p.status),
            injury: p.detail,
            practice: i?.practice ?? null,
            impactPoints: gate(tier, "injuries.adjustments", i?.impact_points ?? null),
            impactNote: i?.impact_note ?? null,
            source: p.source,
            confirmed: p.kind === "official",
            reportTime: p.report_time,
            conflict: p.conflict,
            lateScratch: p.late_scratch,
            longTerm: p.long_term,
          };
        }),
    };
  }
  return {
    ok: true,
    connected: b.data.injuries.connected,
    note: b.data.injuries.note,
    rows: (b.injuries ?? []).map((i) => ({
      team: i.team,
      player: i.player,
      position: i.position,
      status: i.status,
      injury: i.injury,
      practice: i.practice,
      impactPoints: gate(tier, "injuries.adjustments", i.impact_points),
      impactNote: i.impact_note,
    })),
  };
}

export async function getFreshness(league: League): Promise<Freshness> {
  const res = await loadBoard(league);
  return res.ok ? freshness(res.board) : UNAVAILABLE;
}
