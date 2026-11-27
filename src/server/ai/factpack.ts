import "server-only";
import type { ParlayPrice, Pick } from "@/lib/parlay/types";

/**
 * Minimal fact packs for Gemini (TEST, Moose 2026-11-27). Only what a reader of the page already sees: leg labels,
 * the engine's rounded probabilities, stored prices, data flags and injury-report lines. Never model parameters,
 * features, distributions, correlation coefficients, datasets, user details or sportsbook credentials.
 */
export const pctText = (p: number | null | undefined) => (p == null ? "not available" : `${(p * 100).toFixed(1)}%`);
/** +1 for over / home / at-least legs, -1 for under / away legs (from the leg id, which encodes the side). */
export function sideOf(id: string): 1 | -1 {
  const parts = id.split("~");
  const last = parts[parts.length - 1];
  if (parts[2] === "prop") return last === "u" ? -1 : 1;
  if (parts[2] === "total") return parts[3] === "under" ? -1 : 1;
  return parts[3] === "away" ? -1 : 1;
}
const odds = (a: number) => (a > 0 ? `+${a}` : `${a}`);

export interface ParlayPack {
  task: "explain_parlay";
  legs: { id: string; label: string; game: string; type: string; model_probability: string; sportsbook_price: string; market_probability: string; flags: string[] }[];
  parlay: { model_probability: string; range: string; if_unrelated: string; link_between_legs: string; fair_odds: string };
  same_game_links: { legs: string[]; direction: "tend to win together" | "work against each other" }[];
  riskiest_order: string[];
  injury_report: string[];
  notes: string[];
}

export function parlayPack(price: ParlayPrice, injuries: string[]): ParlayPack {
  const ids = price.legs.map((_, i) => `L${i + 1}`);
  const eff = price.correlationEffect;
  return {
    task: "explain_parlay",
    legs: price.legs.map((l, i) => ({
      id: ids[i],
      label: l.label,
      game: l.gameLabel,
      type: l.kind === "prop" ? `player ${l.group.toLowerCase()}` : l.kind,
      model_probability: pctText(l.p),
      sportsbook_price: l.price ? `${odds(l.price.american)}${l.price.bookTitle ? ` (${l.price.bookTitle})` : ""}` : "not stored",
      market_probability: pctText(l.marketP),
      flags: l.warnings.slice(0, 4),
    })),
    parlay: {
      model_probability: price.p === null ? "no single number (not enough history for some links)" : pctText(price.p),
      range: price.range ? `${pctText(price.range[0])} to ${pctText(price.range[1])}` : "not available",
      if_unrelated: pctText(price.independent),
      link_between_legs: eff == null ? "unknown" : eff >= 1.05 ? "legs tend to win together" : eff <= 0.95 ? "legs work against each other" : "legs are close to unrelated",
      fair_odds: price.fairAmerican == null ? "not available" : odds(price.fairAmerican),
    },
    same_game_links: price.pairs
      .map((pr) => {
        const a = price.legs[pr.a];
        const b = price.legs[pr.b];
        if (!a || !b) return null;
        const eff = pr.r * sideOf(a.id) * sideOf(b.id);
        return Math.abs(eff) >= 0.1 ? { legs: [ids[pr.a], ids[pr.b]], direction: (eff > 0 ? "tend to win together" : "work against each other") as "tend to win together" | "work against each other" } : null;
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
      .slice(0, 8),
    riskiest_order: price.legs.map((l, i) => ({ id: ids[i], p: l.p })).sort((a, b) => a.p - b.p).map((x) => x.id),
    injury_report: injuries.slice(0, 10),
    notes: price.warnings.filter((w) => w.level !== "info").map((w) => w.text).slice(0, 6),
  };
}

export interface PicksPack {
  task: "review_picks";
  picks: { id: string; label: string; game: string; model_probability: string; market_probability: string; gap: string; sportsbook_price: string; data_quality: string; risk: string; could_invalidate: string[] }[];
  injury_report: string[];
  history: string;
}

export function picksPack(picks: Pick[], injuries: string[]): PicksPack {
  return {
    task: "review_picks",
    picks: picks.map((p, i) => ({
      id: `P${i + 1}`,
      label: p.leg.label,
      game: p.gameLabel,
      model_probability: pctText(p.leg.p),
      market_probability: pctText(p.leg.marketP),
      gap: p.edge == null ? "not available" : `${(p.edge * 100).toFixed(1)} points`,
      sportsbook_price: p.leg.price ? odds(p.leg.price.american) : "not stored",
      data_quality: p.quality,
      risk: p.risk,
      could_invalidate: p.invalidators.slice(0, 4),
    })),
    injury_report: injuries.slice(0, 12),
    history: "In past NFL seasons, large gaps between the model and closing moneyline prices did not win more often than the price implied.",
  };
}

export const SYSTEM_RULES = [
  "You explain sports betting analysis for Model Room. You are given a JSON fact pack. Use ONLY those facts.",
  "Never calculate, estimate, adjust or state any probability, percentage, odds, line, score or count that is not written in the fact pack exactly as given.",
  "Never invent injuries, lineups, news, matchups, trends or statistics. You have no news access: if the fact pack has no injury report line for something, say the stored report doesn't mention it.",
  "Do not suggest new legs, picks, lines or prices. Do not change the order of anything. Refer to legs and picks by their label.",
  "No bet sizing, no promises, no words like lock, guaranteed or sure thing. Plain, short, confident sentences.",
].join(" ");

export const PARLAY_SCHEMA = {
  type: "OBJECT",
  properties: {
    summary: { type: "STRING", description: "Two or three sentences on what this parlay depends on." },
    legs: { type: "ARRAY", items: { type: "OBJECT", properties: { id: { type: "STRING" }, note: { type: "STRING" } }, required: ["id", "note"] } },
    riskiest: { type: "ARRAY", items: { type: "OBJECT", properties: { id: { type: "STRING" }, reason: { type: "STRING" } }, required: ["id", "reason"] } },
    watch: { type: "ARRAY", items: { type: "STRING" } },
  },
  required: ["summary", "legs", "riskiest", "watch"],
};

export const PICKS_SCHEMA = {
  type: "OBJECT",
  properties: {
    overview: { type: "STRING" },
    picks: { type: "ARRAY", items: { type: "OBJECT", properties: { id: { type: "STRING" }, why: { type: "STRING" }, check: { type: "STRING" } }, required: ["id", "why", "check"] } },
  },
  required: ["overview", "picks"],
};
