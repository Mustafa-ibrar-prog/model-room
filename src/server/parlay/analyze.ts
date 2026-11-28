import "server-only";
import type { ParlayPrice, Pick } from "@/lib/parlay/types";
import { GEMINI_MODEL, generateJson, geminiEnabled } from "@/server/ai/gemini";
import { PARLAY_SCHEMA, PICKS_SCHEMA, SYSTEM_RULES, parlayPack, picksPack } from "@/server/ai/factpack";
import { cacheGet, cacheSet, hash, takeQuota } from "@/server/ai/limits";
import { validateParlayAi, validatePicksAi, validateReviewAi, type ParlayAi, type PicksAi, type ReviewAi } from "@/server/ai/validate";
import { REVIEW_SCHEMA, type ReviewPack } from "./review";
import type { Catalog } from "./legs";
import type { LegEvidence } from "@/lib/parlay/evidence";

/**
 * "Analyze My Parlay" and the picks review (TEST, Moose 2026-11-27). The engine prices first; Gemini only explains the
 * engine's numbers. If Gemini is off, paused, over a cap or fails, the numbers come back anyway with a plain reason.
 */
export type AiStatus<T> =
  | { status: "ok"; model: string; cached: boolean; text: T }
  | { status: "unavailable"; reason: string; message: string };

const MAX_OUT = 1200;

function injuriesFor(catalogs: Catalog[], gameIds: Set<string>): string[] {
  return catalogs.flatMap((c) => [...c.injuries.entries()].filter(([g]) => gameIds.has(g)).flatMap(([, v]) => v));
}

export async function explainParlay(price: ParlayPrice, evidence: Record<string, LegEvidence>, who: { id: string; net: string }, fetchImpl?: typeof fetch): Promise<AiStatus<ParlayAi>> {
  if (!price.ok || !price.legs.length) return { status: "unavailable", reason: "no_price", message: "Price the parlay first." };
  const pack = parlayPack(price, evidence);
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
      "Each leg has an evidence list (ids E1, E2...) with a lean already set by Model Room's rules, and a missing list. Use ONLY that leg's evidence for that leg.",
      "summary: ONE sentence (max 25 words): which legs look solid and which leg the parlay hinges on (weakest_leg). Use player names.",
      "legs, for EVERY leg: hit = the strongest supporting evidence, miss = the strongest warning; each ONE sentence (max 28 words) with cites = the evidence ids it uses (1 to 3).",
      "Prefer matchup, minutes/role, injury and game-environment evidence over recent hit rates when they exist; a recent hit rate is not the chance of hitting.",
      "If no evidence leans against the leg, miss says plainly that the stored data shows no clear warning and cites nothing. Never invent a reason.",
      "assessment: whether this leg's evidence backs the model, is mixed, cuts against it, or is too thin. gap: copy the single most important line from that leg's missing list, or empty.",
      "Refer to players by name, name the stat, write numbers as digits exactly as they appear in the cited evidence. Plain, short words; no hype. No two legs get the same sentence.",
      "watch: at most 2 short items (injury evidence or flags) that could change things before the game; empty if none.",
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

/** The evidence review across the boards: one Gemini call, cached for everyone for 6 hours (same candidates, same answer). */
export async function reviewWithAi(pack: ReviewPack, who: { id: string; net: string }, fetchImpl?: typeof fetch): Promise<AiStatus<ReviewAi>> {
  if (!pack.candidates.length) return { status: "unavailable", reason: "no_candidates", message: "Nothing on the boards to review right now." };
  const key = hash(`review:${GEMINI_MODEL}:${JSON.stringify(pack)}`);
  const hit = cacheGet<ReviewAi>(key);
  if (hit) return { status: "ok", model: GEMINI_MODEL, cached: true, text: hit };
  if (!geminiEnabled()) return { status: "unavailable", reason: "disabled", message: "AI review isn't switched on for this site yet. The evidence counts are complete." };
  const cap = takeQuota(who.id, who.net);
  if (!cap.ok) return { status: "unavailable", reason: cap.scope, message: cap.message };
  const out = await generateJson({
    system: SYSTEM_RULES,
    user: [
      "These candidates come from Model Room's boards, already sorted by fixed rules into two lists: 'closer look' (independent evidence mostly agrees with the model's lean) and 'possible weakness' (evidence or history argues against the model).",
      "For EACH candidate, in the given order: verdict = 'worth investigating' or 'low priority' (how much the evidence deserves a human's time, NOT whether to bet);",
      "why = one sentence (max 28 words) on the strongest evidence, with cites = its evidence ids; risk = one sentence on the strongest reason it could be wrong, with cites, or a plain statement that the stored data shows no clear warning (no cites).",
      "Never re-rank, never add candidates, never state a probability or number that isn't in the cited evidence. A recent hit rate is not a probability. Name the player and stat.",
      "overview: one sentence on what the review found overall, without numbers.",
      `Fact pack:\n${JSON.stringify(pack)}`,
    ].join(" "),
    schema: REVIEW_SCHEMA, maxOutputTokens: 1800, fetchImpl,
  });
  if (!out.ok) return { status: "unavailable", reason: out.reason, message: out.message };
  const v = validateReviewAi(out.json, pack);
  if (!v) return { status: "unavailable", reason: "rejected", message: "The AI answer didn't pass our checks, so it isn't shown." };
  cacheSet(key, v);
  return { status: "ok", model: GEMINI_MODEL, cached: false, text: v };
}
