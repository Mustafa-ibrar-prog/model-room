import "server-only";
import { fairAmerican } from "@/lib/parlay/joint";
import type { LegOption, Pick } from "@/lib/parlay/types";
import type { Catalog } from "./legs";

/**
 * Picks to consider (TEST, Moose 2026-11-27): a statistical list, built only from legs with a stored sportsbook price
 * (NBA points lines on TEST, moneylines). The model's probability and the market's no-vig probability are both stored
 * numbers; the gap between them is the edge. Ranked by edge, discounted for long shots, thin data and injury flags.
 *
 * Honesty rule: historically (NFL moneylines 2023-25 at closing prices, modelroom/parlay/discovery_backtest.py) large
 * model-vs-market gaps did NOT win more often than the price implied. The list is a set of disagreements to check,
 * not a value claim; the page says so. The AI review can explain and flag, never add, remove or re-rank.
 */
const FRESH_HOURS = 12;
/** Gaps above this usually meant the market knew something the model didn't (NFL moneylines 2023-25: biggest-gap bucket lost). */
export const BIG_GAP = 0.1;

export function riskOf(o: LegOption): Pick["risk"] {
  if (o.p < 0.35 || (o.injury && !/^available$/i.test(o.injury))) return "high";
  if (o.p < 0.45 || o.support === "limited") return "medium";
  return "low";
}

export function qualityOf(o: LegOption, now: Date): Pick["quality"] {
  const fresh = o.price?.capturedAt ? now.getTime() - new Date(o.price.capturedAt).getTime() < FRESH_HOURS * 3600_000 : false;
  if ((o.price?.books ?? 0) >= 3 && fresh && o.support !== "limited") return "good";
  if (o.price) return "fair";
  return "thin";
}

const RISK_W = { low: 1, medium: 0.8, high: 0.5 } as const;
const QUAL_W = { good: 1, fair: 0.7, thin: 0.4 } as const;
const pct = (x: number) => `${Math.round(x * 100)}%`;

export function discoverPicks(catalogs: Catalog[], now = new Date(), limit = 12): Pick[] {
  const best = new Map<string, Pick>();
  for (const cat of catalogs) {
    for (const [, l] of cat.legs) {
      const o = l.option;
      if (!o.price || o.marketP == null || o.p < 0.2) continue;
      const edge = Math.round((o.p - o.marketP) * 10000) / 10000;
      if (edge <= 0) continue;
      const risk = edge > BIG_GAP ? "high" : riskOf(o);
      const quality = qualityOf(o, now);
      const score = Math.round(edge * RISK_W[risk] * QUAL_W[quality] * 10000) / 10000;
      const fair = fairAmerican(o.p);
      const why = [`Model ${pct(o.p)} vs market ${pct(o.marketP)}.`];
      if (o.price.books > 1) why.push(`${o.price.books} books posted this line.`);
      if (o.source === "book_line") why.push("Sportsbook line captured this morning.");
      const inv: string[] = [];
      if (fair !== null) inv.push(`Only worth it at ${fair > 0 ? "+" : ""}${fair} or longer.`);
      for (const note of (cat.injuries.get(o.gameId) ?? []).slice(0, 2)) inv.push(`Injury report: ${note}.`);
      if (o.kind === "prop") inv.push("Minutes or role change before tip-off.");
      if (o.kind === "moneyline" && o.league === "nfl") inv.push("A starting quarterback change.");
      if (edge > BIG_GAP) inv.unshift("A gap this big usually means news the model doesn't have (injury, lineup, quarterback).");
      inv.push("Historically, big model-vs-market gaps often meant the market knew more.");
      const pick: Pick = { leg: o, gameLabel: cat.gameLabel.get(o.gameId) ?? o.gameId, edge, quality, risk, score, why, invalidators: inv };
      // one side per player-stat or game result
      const k = o.kind === "prop" ? `${o.league}~${o.gameId}~${o.playerId}~${o.group}` : `${o.league}~${o.gameId}~${o.kind}`;
      const cur = best.get(k);
      if (!cur || cur.score < score) best.set(k, pick);
    }
  }
  return [...best.values()].sort((a, b) => b.score - a.score || b.leg.p - a.leg.p).slice(0, limit);
}
