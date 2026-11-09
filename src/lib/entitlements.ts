import { TIER_ORDER } from "@/config/tiers";
import type { Gate, TierId } from "@/types/domain";

/**
 * Single source of truth for what each plan can see.
 * Used only on the server (data layer + API routes) to decide which values
 * leave the server. The UI reads lock markers; it never makes access decisions.
 */
export type Feature =
  | "games.schedule"
  | "games.basicProjections"
  | "games.edgeFinder.limited"
  | "games.edgeFinder.full"
  | "games.projectedScores"
  | "games.lineMovement"
  | "games.matchupBreakdowns"
  | "injuries.basic"
  | "injuries.adjustments"
  | "props.projections"
  | "props.advanced"
  | "ratings.overall"
  | "ratings.advanced"
  | "insights.daily"
  | "watchlists"
  | "history"
  | "alerts"
  | "reports.download";

const MIN_TIER: Record<Feature, TierId> = {
  "games.schedule": "free",
  "games.basicProjections": "free",
  "games.edgeFinder.limited": "free",
  "games.edgeFinder.full": "plus",
  "games.projectedScores": "plus",
  "games.lineMovement": "plus",
  "games.matchupBreakdowns": "plus",
  "injuries.basic": "free",
  "injuries.adjustments": "plus",
  "props.projections": "plus",
  "props.advanced": "pro",
  "ratings.overall": "free",
  "ratings.advanced": "pro",
  "insights.daily": "free",
  watchlists: "plus",
  history: "pro",
  alerts: "pro",
  "reports.download": "pro",
};

/** How many games a Free viewer gets the model-vs-sportsbook comparison for. */
export const FREE_EDGE_FINDER_LIMIT = 2;

export function requiredTier(feature: Feature): TierId {
  return MIN_TIER[feature];
}

export function canAccess(tier: TierId, feature: Feature): boolean {
  return TIER_ORDER.indexOf(tier) >= TIER_ORDER.indexOf(MIN_TIER[feature]);
}

/** Return the value if allowed, otherwise a lock marker. Never leaks the value. */
export function gate<T>(tier: TierId, feature: Feature, value: T): Gate<T> {
  return canAccess(tier, feature) ? value : { locked: true, requires: MIN_TIER[feature] };
}
