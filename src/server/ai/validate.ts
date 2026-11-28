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
const BANNED = /\b(lock|locks|guarantee[ds]?|can'?t lose|sure thing|free money|bet the house|max bet|hammer|L\d{1,2}|[a-z]+_[a-z_]+|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b/i;
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
export function cleanText(text: unknown, allowed: Set<string>, max = 400, maxSentences = 2): { text: string; removed: number } {
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
  let out = keep.slice(0, maxSentences).join(" ");
  if (out.length > max) out = out.slice(0, max).replace(/\s+\S*$/, "") + "…";
  return { text: out, removed };
}

/** Gemini's words only. Which legs are "most likely" / "least likely" and their order come from the model (factpack). */
export interface ParlayAi { summary: string; legs: { id: string; hit: string; miss: string }[]; watch: string[]; removed: number }

export function validateParlayAi(raw: unknown, pack: { legs: { id: string }[] }): ParlayAi | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const allowed = allowedNumbers(pack);
  const ids = new Set(pack.legs.map((l) => l.id));
  let removed = 0;
  const take = (t: unknown, max?: number, n = 2) => {
    const c = cleanText(t, allowed, max, n);
    removed += c.removed;
    return c.text;
  };
  const summary = take(r.summary, 220, 1);
  const seen = new Set<string>();
  const legs = (Array.isArray(r.legs) ? r.legs : [])
    .filter((x): x is { id: string; hit: unknown; miss: unknown } => !!x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" && ids.has((x as { id: string }).id))
    .filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)))
    .map((x) => ({ id: x.id, hit: take(x.hit, 170, 1), miss: take(x.miss, 170, 1) }));
  // The same sentence under two legs says nothing about either: keep the first, drop the copies.
  const said = new Set<string>();
  for (const l of legs) for (const k of ["hit", "miss"] as const) {
    const key = l[k].toLowerCase().replace(/[^a-z0-9]/g, "");
    if (!key) continue;
    if (said.has(key)) { l[k] = ""; removed++; } else said.add(key);
  }
  const kept = legs.filter((x) => x.hit || x.miss);
  const watch = (Array.isArray(r.watch) ? r.watch : []).slice(0, 2).map((w) => take(w, 120, 1)).filter((w) => w && !/sportsbook price/i.test(w));
  if (!summary && !kept.length) return null;
  return { summary, legs: kept, watch, removed };
}

export interface PicksAi { overview: string; picks: { id: string; why: string; check: string }[]; removed: number }

export function validatePicksAi(raw: unknown, pack: { picks: { id: string }[] }): PicksAi | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const allowed = allowedNumbers(pack);
  const ids = new Set(pack.picks.map((p) => p.id));
  let removed = 0;
  const take = (t: unknown, max?: number, n = 2) => {
    const c = cleanText(t, allowed, max, n);
    removed += c.removed;
    return c.text;
  };
  const overview = take(r.overview, 220);
  const seen = new Set<string>();
  const picks = (Array.isArray(r.picks) ? r.picks : [])
    .filter((x): x is { id: string; why: unknown; check: unknown } => !!x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" && ids.has((x as { id: string }).id))
    .filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)))
    .map((x) => ({ id: x.id, why: take(x.why, 160, 1), check: take(x.check, 160, 1) }))
    .filter((x) => x.why || x.check);
  if (!overview && !picks.length) return null;
  return { overview, picks, removed };
}
