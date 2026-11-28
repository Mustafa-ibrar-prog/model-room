import "server-only";
import type { ParlayPrice, Pick } from "@/lib/parlay/types";
import { likelihoodGroups } from "@/lib/parlay/likelihood";

/**
 * Minimal fact packs for Gemini (TEST, Moose 2026-11-27). Only what a reader of the page already sees: leg labels,
 * the engine's rounded probabilities, stored prices, data flags and injury-report lines. Never model parameters,
 * features, distributions, correlation coefficients, datasets, user details or sportsbook credentials.
 */
/**
 * Polymarket US numbers go to Gemini only when MODELROOM_PM_TO_GEMINI=on. Off by default: sending PMUS data to a third
 * party (Google's free tier may use prompts for training and human review) is redistribution, which the PMUS
 * participant agreement §I.22 allows only "as PMUS expressly permits". Turn on after written permission.
 */
export const pmToGemini = () => process.env.MODELROOM_PM_TO_GEMINI === "on";

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
  legs: { id: string; label: string; game: string; type: string; model_probability: string; sportsbook_price: string; market_probability: string;
    last_10_games?: string; last_10_misses?: string; recent_form?: string; cushion?: string; recent_minutes_any_opponent?: string; opponent?: string; polymarket_probability?: string; model_minus_polymarket?: string; flags: string[];
    /** Set by the model's probability, never by Gemini. */
    group: "most likely to hit" | "least likely to hit"; likelihood_rank: number }[];
  parlay: { model_probability: string; range: string; if_unrelated: string; link_between_legs: string; fair_odds: string };
  same_game_links: { legs: string[]; direction: "tend to win together" | "work against each other" }[];
  /** Leg ids from most to least likely to win (the model's probabilities). */
  likelihood_order: string[];
  weakest_leg: string;
  injury_report: string[];
  notes: string[];
}

/** Words (from the box scores, not the model) that give Gemini something concrete for "could miss". */
type Form = { last_10_misses?: string; recent_form?: string; cushion?: string };
function legForm(l: ParlayPrice["legs"][number]): Form {
  const r = l.last10!;
  const out: Form = { last_10_misses: `missed in ${r.misses} of last ${r.games}` };
  const rate10 = r.hits / r.games;
  const rate5 = r.last5Games ? r.last5Hits / r.last5Games : rate10;
  out.recent_form = rate5 > rate10 + 0.15 ? "hitting more often lately" : rate5 < rate10 - 0.15 ? "cooler lately than over the last 10" : "steady";
  const m = /([\d.]+)\+/.exec(l.label) ?? /under ([\d.]+)/.exec(l.label);
  const k = m ? Number(m[1]) : null;
  if (k !== null && l.kind === "prop") {
    const d = (r.avg - k) / Math.max(1, k);
    const over = sideOf(l.id) > 0;
    out.cushion = Math.abs(d) < 0.08 ? "average sits right around the line" : (d > 0) === over ? "average is comfortably on the winning side of the line" : "average is on the losing side of the line";
  }
  return out;
}

export function parlayPack(price: ParlayPrice, injuries: string[]): ParlayPack {
  const ids = price.legs.map((_, i) => `L${i + 1}`);
  const eff = price.correlationEffect;
  const { order, least } = likelihoodGroups(price.legs.map((l) => l.p));
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
      ...(l.last10 ? { last_10_games: l.last10.text, ...legForm(l) } : {}),
      ...(l.context?.usage ? { recent_minutes_any_opponent: l.context.usage } : {}),
      ...(l.context?.opp ? { opponent: l.context.opp } : {}),
      ...(pmToGemini() && l.polymarket?.implied != null ? { polymarket_probability: pctText(l.polymarket.implied), model_minus_polymarket: `${((l.p - l.polymarket.implied) * 100).toFixed(1)} points` } : {}),
      flags: l.warnings.filter((w) => !/sportsbook price/i.test(w)).slice(0, 4),
      group: least.has(i) ? "least likely to hit" as const : "most likely to hit" as const,
      likelihood_rank: order.indexOf(i) + 1,
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
    likelihood_order: order.map((i) => ids[i]),
    weakest_leg: ids[order[order.length - 1]],
    injury_report: injuries.slice(0, 10),
    notes: price.warnings.filter((w) => w.level !== "info").map((w) => w.text).slice(0, 6),
  };
}

export interface PicksPack {
  task: "review_picks";
  picks: { id: string; label: string; game: string; model_probability: string; market: string; market_probability: string; gap: string; sportsbook_price: string; data_quality: string; risk: string; could_invalidate: string[] }[];
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
      market_probability: p.benchmark === "polymarket" && !pmToGemini() ? "withheld" : pctText(p.marketP),
      market: p.benchmark === "polymarket" ? (pmToGemini() ? "Polymarket US" : "exchange (withheld)") : "sportsbooks",
      gap: p.edge == null ? "not available" : p.benchmark === "polymarket" && !pmToGemini() ? "withheld" : `${(p.edge * 100).toFixed(1)} points`,
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
  "Be brief: no background, no generic advice, no restating the numbers unless they matter.",
].join(" ");

export const PARLAY_SCHEMA = {
  type: "OBJECT",
  properties: {
    summary: { type: "STRING", description: "One sentence: where this parlay is solid and which leg it hinges on." },
    legs: { type: "ARRAY", items: { type: "OBJECT", properties: { id: { type: "STRING" }, hit: { type: "STRING" }, miss: { type: "STRING" } }, required: ["id", "hit", "miss"] } },
    watch: { type: "ARRAY", items: { type: "STRING" } },
  },
  required: ["summary", "legs", "watch"],
};

export const PICKS_SCHEMA = {
  type: "OBJECT",
  properties: {
    overview: { type: "STRING" },
    picks: { type: "ARRAY", items: { type: "OBJECT", properties: { id: { type: "STRING" }, why: { type: "STRING" }, check: { type: "STRING" } }, required: ["id", "why", "check"] } },
  },
  required: ["overview", "picks"],
};
