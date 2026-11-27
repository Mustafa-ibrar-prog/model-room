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
    user: `Explain this parlay for the reader: what it depends on, a short note per leg, the riskiest legs (use riskiest_order and the flags), and what to watch before the games. Fact pack:\n${JSON.stringify(pack)}`,
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
    user: `For each pick, say in one sentence why it is on the list (from the facts) and in one sentence what to check before using it (from could_invalidate and the injury report). Keep the list order. One short overview sentence that repeats the history note. Fact pack:\n${JSON.stringify(pack)}`,
    schema: PICKS_SCHEMA, maxOutputTokens: MAX_OUT, fetchImpl,
  });
  if (!out.ok) return { status: "unavailable", reason: out.reason, message: out.message };
  const v = validatePicksAi(out.json, pack);
  if (!v) return { status: "unavailable", reason: "rejected", message: "The AI answer didn't pass our checks, so it isn't shown." };
  cacheSet(key, v);
  return { status: "ok", model: GEMINI_MODEL, cached: false, text: v };
}
