import "server-only";

/**
 * Gemini's answer is text for people to read, never numbers for the page (TEST, Moose 2026-11-27). Before anything is
 * shown:
 *   - ids must be ones the fact pack listed; anything else is dropped (Gemini can't add legs or picks)
 *   - every sentence is checked for numbers: a percentage, American odds, decimal or any number above 10 that is not
 *     written in the fact pack is removed with its sentence (Gemini can't state or change a probability)
 *   - sentences with promises ("lock", "guaranteed") are removed
 *   - lengths are capped
 * The page always shows the engine's numbers from the pricing step, never numbers from this text.
 */
const BANNED = /\b(lock|locks|guarantee[ds]?|can'?t lose|sure thing|free money|bet the house|max bet|hammer)\b/i;
const NUM = /[+-]?\d+(?:[.,]\d+)?\s*%?/g;

/** All number tokens that appear anywhere in the fact pack, normalised. */
export function allowedNumbers(pack: unknown): Set<string> {
  const s = new Set<string>();
  const text = JSON.stringify(pack);
  for (const m of text.matchAll(NUM)) {
    const t = norm(m[0]);
    s.add(t);
    s.add(t.replace(/%$/, ""));
    s.add(t.replace(/^\+/, ""));
  }
  return s;
}

function norm(t: string) {
  return t.replace(/\s+/g, "").replace(",", ".");
}

/** Removes sentences with numbers the pack doesn't contain, or with banned words. Returns the text and how much was cut. */
export function cleanText(text: unknown, allowed: Set<string>, max = 400): { text: string; removed: number } {
  if (typeof text !== "string") return { text: "", removed: 0 };
  const sentences = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s+/);
  let removed = 0;
  const keep: string[] = [];
  for (const s of sentences) {
    if (!s) continue;
    if (BANNED.test(s)) {
      removed++;
      continue;
    }
    let ok = true;
    for (const m of s.matchAll(NUM)) {
      const t = norm(m[0]);
      const bare = Number(t.replace(/[%+]/g, ""));
      const plainSmallInt = /^\d+$/.test(t) && bare <= 10;
      if (plainSmallInt) continue;
      if (!(allowed.has(t) || allowed.has(t.replace(/^\+/, "")) || allowed.has(t.replace(/%$/, "")))) {
        ok = false;
        break;
      }
      // a bare number that only appears in the pack as part of a label is fine; a percentage must appear as a percentage
      if (t.endsWith("%") && !allowed.has(t)) {
        ok = false;
        break;
      }
    }
    if (ok) keep.push(s);
    else removed++;
  }
  let out = keep.join(" ");
  if (out.length > max) out = out.slice(0, max).replace(/\s+\S*$/, "") + "…";
  return { text: out, removed };
}

export interface ParlayAi { summary: string; legs: { id: string; note: string }[]; riskiest: { id: string; reason: string }[]; watch: string[]; removed: number }

export function validateParlayAi(raw: unknown, pack: { legs: { id: string }[] }): ParlayAi | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const allowed = allowedNumbers(pack);
  const ids = new Set(pack.legs.map((l) => l.id));
  let removed = 0;
  const take = (t: unknown, max?: number) => {
    const c = cleanText(t, allowed, max);
    removed += c.removed;
    return c.text;
  };
  const summary = take(r.summary, 500);
  const legs = (Array.isArray(r.legs) ? r.legs : [])
    .filter((x): x is { id: string; note: unknown } => !!x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" && ids.has((x as { id: string }).id))
    .slice(0, pack.legs.length)
    .map((x) => ({ id: x.id, note: take(x.note, 260) }))
    .filter((x) => x.note);
  const riskiest = (Array.isArray(r.riskiest) ? r.riskiest : [])
    .filter((x): x is { id: string; reason: unknown } => !!x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" && ids.has((x as { id: string }).id))
    .slice(0, 3)
    .map((x) => ({ id: x.id, reason: take(x.reason, 220) }))
    .filter((x) => x.reason);
  const watch = (Array.isArray(r.watch) ? r.watch : []).slice(0, 4).map((w) => take(w, 180)).filter(Boolean);
  if (!summary && !legs.length) return null;
  return { summary, legs, riskiest, watch, removed };
}

export interface PicksAi { overview: string; picks: { id: string; why: string; check: string }[]; removed: number }

export function validatePicksAi(raw: unknown, pack: { picks: { id: string }[] }): PicksAi | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const allowed = allowedNumbers(pack);
  const ids = new Set(pack.picks.map((p) => p.id));
  let removed = 0;
  const take = (t: unknown, max?: number) => {
    const c = cleanText(t, allowed, max);
    removed += c.removed;
    return c.text;
  };
  const overview = take(r.overview, 400);
  const seen = new Set<string>();
  const picks = (Array.isArray(r.picks) ? r.picks : [])
    .filter((x): x is { id: string; why: unknown; check: unknown } => !!x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" && ids.has((x as { id: string }).id))
    .filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)))
    .map((x) => ({ id: x.id, why: take(x.why, 240), check: take(x.check, 200) }))
    .filter((x) => x.why || x.check);
  if (!overview && !picks.length) return null;
  return { overview, picks, removed };
}
