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
export interface Claim { text: string; cites: string[] }
export type Assessment = "evidence backs the model" | "evidence is mixed" | "evidence cuts against the model" | "too little evidence";
export interface ParlayAi { summary: string; legs: { id: string; hit: Claim; miss: Claim; assessment: Assessment | null; gap: string }[]; watch: string[]; removed: number }
const ASSESS = new Set<Assessment>(["evidence backs the model", "evidence is mixed", "evidence cuts against the model", "too little evidence"]);

/** A claim may only use numbers from the evidence items it cites (plus its own label and model chance): no borrowing
 *  another leg's figures, no numbers from nowhere. Citations must be that leg's own items. */
export function makeClaim(pl: PackLeg, v: unknown): { claim: Claim; removed: number } {
  const items = new Map((pl.evidence ?? []).map((e) => [e.id, e]));
  const o = (v && typeof v === "object" ? v : { text: v, cites: [] }) as { text?: unknown; cites?: unknown };
  const cites = (Array.isArray(o.cites) ? o.cites : []).filter((c): c is string => typeof c === "string" && items.has(c)).slice(0, 3);
  const allow = allowedNumbers({ label: pl.label, p: pl.model_probability, e: cites.map((c) => items.get(c)!.text) });
  const c = cleanText(o.text, allow, 200, 1);
  return { claim: { text: c.text, cites: c.text ? [...new Set(cites)] : [] }, removed: c.removed };
}

export interface ReviewAi { overview: string; candidates: { id: string; verdict: "worth investigating" | "low priority"; why: Claim; risk: Claim }[]; removed: number }

export function validateReviewAi(raw: unknown, pack: { candidates: PackLeg[] }): ReviewAi | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  let removed = 0;
  const overview = cleanText(r.overview, allowedNumbers({}), 220, 1);
  removed += overview.removed;
  const seen = new Set<string>();
  const out: ReviewAi["candidates"] = [];
  for (const x of Array.isArray(r.candidates) ? r.candidates : []) {
    if (!x || typeof x !== "object") continue;
    const o = x as { id?: unknown; verdict?: unknown; why?: unknown; risk?: unknown };
    const pl = pack.candidates.find((c) => c.id === o.id);
    if (!pl || seen.has(pl.id)) continue;
    seen.add(pl.id);
    if (o.verdict !== "worth investigating" && o.verdict !== "low priority") continue;
    const w = makeClaim(pl, o.why), k = makeClaim(pl, o.risk);
    removed += w.removed + k.removed;
    out.push({ id: pl.id, verdict: o.verdict, why: w.claim, risk: k.claim });
  }
  if (!out.length) return null;
  return { overview: overview.text, candidates: out, removed };
}

type PackLeg = { id: string; label?: string; model_probability?: string; evidence?: { id: string; text: string }[]; missing?: string[] };
export function validateParlayAi(raw: unknown, pack: { legs: PackLeg[] }): ParlayAi | null {
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
    .filter((x): x is { id: string; hit: unknown; miss: unknown; assessment?: unknown; gap?: unknown } => !!x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" && ids.has((x as { id: string }).id))
    .filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)))
    .map((x) => {
      const pl = pack.legs.find((l) => l.id === x.id)!;
      const claim = (v: unknown): Claim => { const c = makeClaim(pl, v); removed += c.removed; return c.claim; };
      const assessment = typeof x.assessment === "string" && ASSESS.has(x.assessment as Assessment) ? (x.assessment as Assessment) : null;
      // "gap" must be one of this leg's own missing-data lines (the AI picks; it can't invent a gap).
      const gap = typeof x.gap === "string" ? (pl.missing ?? []).find((m) => norm2(m) === norm2(x.gap as string)) ?? "" : "";
      return { id: x.id, hit: claim(x.hit), miss: claim(x.miss), assessment, gap };
    });
  // The same sentence under two legs says nothing about either: keep the first, drop the copies.
  const said = new Set<string>();
  for (const l of legs) for (const k of ["hit", "miss"] as const) {
    const key = l[k].text.toLowerCase().replace(/[^a-z0-9]/g, "");
    if (!key) continue;
    if (said.has(key)) { l[k] = { text: "", cites: [] }; removed++; } else said.add(key);
  }
  const kept = legs.filter((x) => x.hit.text || x.miss.text || x.assessment);
  const watch = (Array.isArray(r.watch) ? r.watch : []).slice(0, 2).map((w) => take(w, 120, 1)).filter((w) => w && !/sportsbook price/i.test(w));
  if (!summary && !kept.length) return null;
  return { summary, legs: kept, watch, removed };
}

const norm2 = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, "");

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
