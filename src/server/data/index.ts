import "server-only";
import { FREE_EDGE_FINDER_LIMIT, canAccess, gate } from "@/lib/entitlements";
import { getProvider } from "@/server/providers";
import type {
  DailyInsight,
  DataEnvelope,
  GameProjection,
  InjuryReport,
  League,
  PlayerPropProjection,
  TeamRating,
  TierId,
} from "@/types/domain";

/**
 * Data Access Layer.
 *
 * The only path from a provider to a page or API route. Every premium field
 * is passed through `gate()` here, so a viewer's response never contains
 * values their plan does not include — not in HTML, not in RSC payloads,
 * not in JSON.
 */

function envelope<T>(tier: TierId, data: T): DataEnvelope<T> {
  const { info } = getProvider();
  return {
    meta: { source: info.source, generatedBy: info.name, note: info.note },
    viewerTier: tier,
    data,
  };
}

const round1 = (n: number) => Math.round(n * 10) / 10;

export async function getGameBoard(league: League, tier: TierId): Promise<DataEnvelope<GameProjection[]>> {
  const raw = await getProvider().getGames(league);
  const fullEdges = canAccess(tier, "games.edgeFinder.full");

  const rows = raw.map((g, i): GameProjection => {
    // Edge = gap between market and model. Arithmetic only, not a model.
    // Spread edge > 0 means the model likes the home side more than the market.
    const spreadEdge = round1(g.marketSpread - g.modelSpread);
    const totalEdge = round1(g.modelTotal - g.marketTotal);
    const edgeVisible = fullEdges || i < FREE_EDGE_FINDER_LIMIT;
    const edgeFeature = edgeVisible ? "games.edgeFinder.limited" : "games.edgeFinder.full";

    return {
      id: g.id,
      league: g.league,
      slot: g.slot,
      away: g.away,
      home: g.home,
      marketSpread: g.marketSpread,
      marketTotal: g.marketTotal,
      modelSpread: gate(tier, "games.basicProjections", g.modelSpread),
      modelTotal: gate(tier, "games.basicProjections", g.modelTotal),
      spreadEdge: gate(tier, edgeFeature, spreadEdge),
      totalEdge: gate(tier, edgeFeature, totalEdge),
      projectedScore: gate(tier, "games.projectedScores", g.projectedScore),
      openingSpread: gate(tier, "games.lineMovement", g.openingSpread),
      matchupNote: gate(tier, "games.matchupBreakdowns", g.matchupNote),
    };
  });

  return envelope(tier, rows);
}

export async function getInjuryReport(league: League, tier: TierId): Promise<DataEnvelope<InjuryReport[]>> {
  const raw = await getProvider().getInjuries(league);
  return envelope(
    tier,
    raw.map((r) => ({
      id: r.id,
      league: r.league,
      player: r.player,
      team: r.team,
      position: r.position,
      status: r.status,
      detail: r.detail,
      spreadImpact: gate(tier, "injuries.adjustments", r.spreadImpact),
      totalImpact: gate(tier, "injuries.adjustments", r.totalImpact),
    })),
  );
}

/** Returns null data when the viewer's plan has no prop access at all. */
export async function getPropBoard(
  league: League,
  tier: TierId,
): Promise<DataEnvelope<PlayerPropProjection[] | null>> {
  if (!canAccess(tier, "props.projections")) return envelope(tier, null);
  const raw = await getProvider().getProps(league);
  return envelope(
    tier,
    raw.map((p) => ({
      id: p.id,
      league: p.league,
      player: p.player,
      team: p.team,
      opponent: p.opponent,
      market: p.market,
      line: p.line,
      projection: p.projection,
      edge: round1(p.projection - p.line),
      overShare: gate(tier, "props.advanced", p.overShare),
      range: gate(tier, "props.advanced", p.range),
    })),
  );
}

export async function getRatings(league: League, tier: TierId): Promise<DataEnvelope<TeamRating[]>> {
  const raw = await getProvider().getRatings(league);
  const sorted = [...raw].sort((a, b) => b.overall - a.overall);
  return envelope(
    tier,
    sorted.map((r, i) => ({
      rank: i + 1,
      team: r.team,
      league: r.league,
      overall: r.overall,
      offense: gate(tier, "ratings.advanced", r.offense),
      defense: gate(tier, "ratings.advanced", r.defense),
      pace: gate(tier, "ratings.advanced", r.pace),
      scheduleStrength: gate(tier, "ratings.advanced", r.scheduleStrength),
    })),
  );
}

export async function getDailyInsights(tier: TierId): Promise<DataEnvelope<DailyInsight[]>> {
  return envelope(tier, await getProvider().getInsights());
}

export function getDataSourceInfo() {
  return getProvider().info;
}
