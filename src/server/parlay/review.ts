import "server-only";
import { propSelection } from "@/lib/parlay/cardMath";
import type { LegEvidence } from "@/lib/parlay/evidence";
import type { LegOption } from "@/lib/parlay/types";
import { buildEvidence, type Sources } from "@/server/ai/evidence";
import { pmToGemini, pctText } from "@/server/ai/factpack";
import type { Catalog } from "./legs";

/**
 * Evidence review across the boards (TEST, Moose 2026-11-28). SEPARATE from the model's ranking and from "Picks to
 * consider": it never creates picks, changes probabilities or re-ranks the model. For each player and stat it takes
 * the line a market quotes (else the model's coin-flip line), the side the model leans, the stored evidence for that
 * exact leg, and sorts by how well the evidence lines up, using fixed rules:
 *
 *   closer look     evidence (not the model's own numbers) leans mostly the model's way
 *   possible weakness   the model leans one way and most evidence leans the other, or the model's chance is far from
 *                   the player's recent hit rate, or the model flags limited history
 *
 * Evidence balance is a count of independent facts, not a probability. Gemini may then say which deserve a look; it
 * sees the same evidence lists and nothing else.
 */
export interface ReviewItem {
  leg: LegOption;
  gameLabel: string;
  /** Market this line is compared with, when one quotes it. */
  market: { kind: "sportsbook" | "polymarket"; p: number } | null;
  gap: number | null;
  supports: number;
  against: number;
  quality: number;
  flags: string[];
  list: "closer look" | "possible weakness";
}

const OUTER = new Set(["model"]);
const KIND_GROUP: Record<string, string> = { form: "form", split: "form", usage: "role", lineup: "role", matchup: "matchup", injury: "injury", environment: "environment", weather: "environment", market: "market" };

export function reviewBoards(catalogs: Catalog[], src: Sources, limits = { closer: 8, weak: 5 }): { items: ReviewItem[]; evidence: Record<string, LegEvidence>; scanned: number } {
  const picked: { leg: LegOption; cat: Catalog }[] = [];
  for (const cat of catalogs) {
    for (const [, c] of cat.cards) {
      for (const card of c.props) {
        if (!card.thresholds.length) continue;
        const near = (ks: number[]) => ks.filter((k) => card.thresholds.includes(k)).sort((a, b) => Math.abs(a - card.projection) - Math.abs(b - card.projection))[0];
        let K = card.bookLine !== null && card.thresholds.includes(card.bookLine + 0.5) ? card.bookLine + 0.5 : near(card.pm.map((x) => x.line));
        if (K === undefined) {
          K = card.thresholds.reduce((a, b) => (Math.abs((propSelection(card, b, 1).p ?? 0) - 0.5) < Math.abs((propSelection(card, a, 1).p ?? 0) - 0.5) ? b : a));
        }
        const over = propSelection(card, K, 1);
        const side: 1 | -1 = (over.p ?? 0) >= 0.5 ? 1 : -1;
        const sel = side > 0 ? over : propSelection(card, K, -1);
        const leg = cat.resolve(sel.id)?.option;
        if (leg) picked.push({ leg, cat });
      }
    }
  }
  const evidence = buildEvidence(picked.map((x) => x.leg), src);
  const all: ReviewItem[] = [];
  for (const { leg, cat } of picked) {
    const ev = evidence[leg.id];
    if (!ev) continue;
    // One vote per kind of evidence (form, matchup, minutes, injuries...), so three ways of saying "he's been cold"
    // count once. The model's own reasoning doesn't vote.
    const net = new Map<string, number>();
    for (const x of ev.items) if (!OUTER.has(x.kind)) net.set(KIND_GROUP[x.kind] ?? x.kind, (net.get(KIND_GROUP[x.kind] ?? x.kind) ?? 0) + (x.lean === "supports" ? 1 : x.lean === "against" ? -1 : 0));
    const S = [...net.values()].filter((v) => v > 0).length;
    const A = [...net.values()].filter((v) => v < 0).length;
    const market = leg.marketP != null ? { kind: "sportsbook" as const, p: leg.marketP } : leg.polymarket?.implied != null ? { kind: "polymarket" as const, p: leg.polymarket.implied } : null;
    const gap = market ? Math.round((leg.p - market.p) * 1000) / 1000 : null;
    const flags: string[] = [];
    if (ev.items.some((x) => x.kind === "injury" && x.lean !== "neutral")) flags.push("injury-related");
    if (gap !== null && Math.abs(gap) >= 0.06) flags.push(gap > 0 ? "model above market" : "model below market");
    const l10 = leg.last10;
    if (l10 && l10.games >= 8 && Math.abs(leg.p - l10.hits / l10.games) >= 0.3) flags.push("model far from recent hit rate");
    if (leg.support === "limited") flags.push("limited history");
    const quality = Math.round(((S - A) / Math.sqrt(S + A + 1)) * 100) / 100;
    const weak = (A >= S + 2 && leg.p >= 0.55) || flags.includes("model far from recent hit rate") || flags.includes("limited history");
    all.push({ leg, gameLabel: cat.gameLabel.get(leg.gameId) ?? leg.gameId, market, gap, supports: S, against: A, quality, flags, list: weak ? "possible weakness" : "closer look" });
  }
  // Priority: evidence balance first, then a market to compare with, then an injury angle; one entry per player.
  const pri = (x: ReviewItem) => x.quality + (x.market ? 0.75 : 0) + (x.flags.includes("injury-related") ? 0.5 : 0);
  const onePer = (xs: ReviewItem[], n: number) => {
    const seen = new Set<string>();
    return xs.filter((x) => { const k = x.leg.playerId ?? x.leg.id; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, n);
  };
  const closer = onePer(all.filter((x) => x.list === "closer look" && x.supports > x.against && x.leg.p >= 0.55 && x.leg.p <= 0.85)
    .sort((a, b) => pri(b) - pri(a) || Math.abs(b.gap ?? 0) - Math.abs(a.gap ?? 0)), limits.closer);
  const weak = onePer(all.filter((x) => x.list === "possible weakness")
    .sort((a, b) => (b.against - b.supports) + (b.market ? 0.75 : 0) - ((a.against - a.supports) + (a.market ? 0.75 : 0)) || b.leg.p - a.leg.p), limits.weak);
  const items = [...closer, ...weak];
  return { items, evidence: Object.fromEntries(items.map((x) => [x.leg.id, evidence[x.leg.id]])), scanned: all.length };
}

export interface ReviewPack {
  task: "review_boards";
  candidates: { id: string; label: string; game: string; list: string; model_probability: string; market: string; flags: string[];
    evidence: { id: string; kind: string; text: string; lean: string }[]; missing: string[] }[];
}

export function reviewPack(items: ReviewItem[], evidence: Record<string, LegEvidence>): ReviewPack {
  return {
    task: "review_boards",
    candidates: items.map((x, i) => ({
      id: `C${i + 1}`,
      label: x.leg.label,
      game: x.gameLabel,
      list: x.list,
      model_probability: pctText(x.leg.p),
      market: !x.market ? "no market price" : x.market.kind === "polymarket" && !pmToGemini() ? "exchange price (withheld)" : `${x.market.kind} ${pctText(x.market.p)}`,
      flags: x.flags.filter((f) => pmToGemini() || x.market?.kind !== "polymarket" || !f.startsWith("model ") || f.includes("recent")),
      evidence: (evidence[x.leg.id]?.items ?? []).map((e) => ({ id: e.id, kind: e.kind, text: e.text, lean: e.lean })),
      missing: (evidence[x.leg.id]?.missing ?? []).slice(0, 4),
    })),
  };
}

export const REVIEW_SCHEMA = {
  type: "OBJECT",
  properties: {
    overview: { type: "STRING" },
    candidates: { type: "ARRAY", items: { type: "OBJECT", properties: {
      id: { type: "STRING" },
      verdict: { type: "STRING", enum: ["worth investigating", "low priority"] },
      why: { type: "OBJECT", properties: { text: { type: "STRING" }, cites: { type: "ARRAY", items: { type: "STRING" } } }, required: ["text", "cites"] },
      risk: { type: "OBJECT", properties: { text: { type: "STRING" }, cites: { type: "ARRAY", items: { type: "STRING" } } }, required: ["text", "cites"] },
    }, required: ["id", "verdict", "why", "risk"] } },
  },
  required: ["overview", "candidates"],
};
