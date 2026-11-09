import type { TierId } from "@/types/domain";

/**
 * Plan definitions shown on the pricing page.
 * Feature access rules live in src/lib/entitlements.ts — keep both in sync.
 */
export interface Plan {
  id: TierId;
  name: string;
  priceMonthly: number;
  summary: string;
  features: string[];
  excluded?: string[];
}

export const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    priceMonthly: 0,
    summary: "Follow the slate and see where the model lands on spreads and totals.",
    features: [
      "NFL and NBA game schedules",
      "Basic game spread and total projections",
      "Daily insights",
      "Basic injury reports",
      "Model vs sportsbook comparison for a few games",
    ],
    excluded: ["Player props"],
  },
  {
    id: "plus",
    name: "Plus",
    priceMonthly: 14.99,
    summary: "The full board for bettors who check every game.",
    features: [
      "Full NFL and NBA projections",
      "Player prop projections",
      "Injury adjustments",
      "Line movement",
      "Matchup breakdowns",
      "Watchlists",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    priceMonthly: 29.99,
    summary: "Model history, deeper analytics and tools for serious volume.",
    features: [
      "Everything in Plus",
      "Historical model data",
      "Advanced analytics",
      "Advanced player prop analysis",
      "Customizable alerts",
      "Downloadable reports",
    ],
  },
];

export const TIER_ORDER: TierId[] = ["free", "plus", "pro"];

export function tierName(id: TierId): string {
  return PLANS.find((p) => p.id === id)?.name ?? id;
}
