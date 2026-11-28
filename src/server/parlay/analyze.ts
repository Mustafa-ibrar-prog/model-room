import "server-only";
import type { ParlayPrice, Pick } from "@/lib/parlay/types";
import { GEMINI_MODEL, generateJson, geminiEnabled } from "@/server/ai/gemini";
import { PARLAY_SCHEMA, PICKS_SCHEMA, SYSTEM_RULES, parlayPack, picksPack } from "@/server/ai/factpack";
import { cacheGet, cacheSet, hash, takeQuota } from "@/server/ai/limits";
import { validateParlayAi, validatePicksAi, type ParlayAi, type PicksAi } from "@/server/ai/validate";
import type { Catalog } from "./legs";

/**
 * "Analyze My Parlay" and the picks review (TEST, Moose 2026-11-27). The engine prices first; Gemini only explains the
 * engine's numbers. If Gemini is off, paused, over a cap or fails, the numbers come back anyway with a plain reason.
 */
export type AiStatus<T> =
  | { status: "ok"; model: string; cached: boolean; text: T }
  | { status: "unavailable"; reason: string; message: string };

const MAX_OUT = 700;

function injuriesFor(catalogs: Catalog[], gameIds: Set<string>): string[] {
  return catalogs.flatMap((c) => [...c.injuries.entries()].filter(([g]) => gameIds.has(g)).flatMap(([, v]) => v));
}

export async function explainParlay(price: ParlayPrice, catalogs: Catalog[], who: { id: string; net: string }, fetchImpl?: typeof fetch): Promise<AiStatus<ParlayAi>> {
  if (!price.ok || !price.legs.length) return { status: "unavailable", reason: "no_price", message: "Price the parlay first." };
  const pack = parlayPack(price, injuriesFor(catalogs, new Set(price.legs.map((l) => l.gameId))));
  const key = hash(`parlay:${GEMINI_MODEL}:${JSON.stringify(pack)}`);
  const hit = cacheGet<ParlayAi>(key);
  if (hit) return { status: "ok", model: GEMINI_MODEL, cached: true, text: hit };
  if (!geminiEnabled()) return { status: "unavailable", reason: "disabled", message: "AI explanations aren't switched on for this site yet. The numbers above are complete." };
  const cap = takeQuota(who.id, who.net);
  if (!cap.ok) return { status: "unavailable", reason: cap.scope, message: cap.message };
  const out = await generateJson({
    system: SYSTEM_RULES,
    user: [
      "Explain this parlay leg by leg. The legs are already ranked and grouped by the model (likelihood_order, group, weakest_leg): keep that, never re-rank.",
      "summary: ONE sentence (max 25 words): which legs look solid and which leg the parlay hinges on (weakest_leg).",
      "legs: for EVERY leg: hit = one sentence (max 22 words) on the best reason it could hit; miss = one sentence (max 22 words) on the main way it could miss.",
      "hit: the strongest supporting fact (cushion, recent_form, recent minutes, a same-game link that helps). miss: the strongest warning (model_vs_recent when the model is less optimistic, cushion, recent_form, last_10_misses, a link that works against it, flags, injury_report), with a few words on why it matters.",
      "Never just restate the threshold, and don't repeat the 'hit in N of last 10' line the page already shows unless it is the only fact.",
      "Refer to players by name. Never write leg ids like L1 or field names. Write in your own words: no two sentences in the answer may be the same or near-copies, and never quote a fact pack phrase word for word.",
      "When model_vs_recent says the model chance is well below the recent hit rate, say what that means for this player (e.g. the recent run may flatter him), not just that the model disagrees.",
      "Use only last_10_games, recent_minutes_any_opponent, opponent, same_game_links, injury_report and flags. recent_minutes_any_opponent is his last 5 games against anyone, NOT against this opponent; never say 'against' the opponent for it.",
      "Be specific to each leg; don't repeat the same reason across legs; don't mention missing sportsbook prices.",
      "watch: at most 2 short items from injury_report or flags that could change things before tip-off; empty if none.",
      `Fact pack:\n${JSON.stringify(pack)}`,
    ].join(" "),
    schema: PARLAY_SCHEMA, maxOutputTokens: MAX_OUT, fetchImpl,
  });
  if (!out.ok) return { status: "unavailable", reason: out.reason, message: `${out.message} The numbers above are complete.` };
  const v = validateParlayAi(out.json, pack);
  if (!v) return { status: "unavailable", reason: "rejected", message: "The AI answer didn't pass our checks, so it isn't shown. The numbers above are complete." };
  cacheSet(key, v);
  return { status: "ok", model: GEMINI_MODEL, cached: false, text: v };
}

export async function reviewPicks(picks: Pick[], catalogs: Catalog[], who: { id: string; net: string }, fetchImpl?: typeof fetch): Promise<AiStatus<PicksAi>> {
  if (!picks.length) return { status: "unavailable", reason: "no_picks", message: "No priced picks to review right now." };
  const pack = picksPack(picks, injuriesFor(catalogs, new Set(picks.map((p) => p.leg.gameId))));
  const key = hash(`picks:${GEMINI_MODEL}:${JSON.stringify(pack)}`);
  const hit = cacheGet<PicksAi>(key);
  if (hit) return { status: "ok", model: GEMINI_MODEL, cached: true, text: hit };
  if (!geminiEnabled()) return { status: "unavailable", reason: "disabled", message: "AI review isn't switched on for this site yet." };
  const cap = takeQuota(who.id, who.net);
  if (!cap.ok) return { status: "unavailable", reason: cap.scope, message: cap.message };
  const out = await generateJson({
    system: SYSTEM_RULES,
    user: `Each pick is a disagreement between Model Room and a market. For each pick: why = one sentence (max 20 words) on what the disagreement might reflect, from the facts only; check = one sentence (max 20 words) from could_invalidate and the injury report. Keep the list order. overview: one sentence that repeats the history note. Fact pack:\n${JSON.stringify(pack)}`,
    schema: PICKS_SCHEMA, maxOutputTokens: MAX_OUT, fetchImpl,
  });
  if (!out.ok) return { status: "unavailable", reason: out.reason, message: out.message };
  const v = validatePicksAi(out.json, pack);
  if (!v) return { status: "unavailable", reason: "rejected", message: "The AI answer didn't pass our checks, so it isn't shown." };
  cacheSet(key, v);
  return { status: "ok", model: GEMINI_MODEL, cached: false, text: v };
}
