import { formatProjection } from "@/lib/format";
import type { PickRecord, PickRow } from "@/types/history";

/** Plain-English text for a stored pick and for what happened. Nothing here decides a result: that is stored. */
const n = (x: number) => (Number.isInteger(x) ? x.toFixed(0) : x.toFixed(1));
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${n(Math.abs(x))}`;

export type Final = { home: number; away: number } | null;
export type GameCtx = { home: string; away: string; final: Final };

/** "BOS to win", "BOS −7.5", "Over 225.5", "20+ points", "Under 20 points". */
export function pickText(p: PickRow): string {
  if (p.market === "moneyline") return `${p.team} to win`;
  if (p.market === "spread") return `${p.team} ${p.line === 0 ? "pick'em" : signed(p.line ?? 0)}`;
  if (p.market === "total") return `${p.selection === "over" ? "Over" : "Under"} ${n(p.line ?? 0)}`;
  const stat = (p.stat_label ?? p.stat ?? "").toLowerCase();
  const k = n(p.line ?? 0);
  if (p.selection === "at_least") return `${k}+ ${stat}`;
  if (p.selection === "below") return `Under ${k} ${stat}`;
  return `${p.selection === "over" ? "Over" : "Under"} ${k} ${stat}`;
}

/** What actually happened, in the same terms as the pick. Empty until there is a verified result. */
export function outcomeText(p: PickRow, g: GameCtx): string {
  if (p.result === "cancelled") return "Game not played";
  if (p.market === "prop") {
    if (p.result === "void") return "Did not play";
    return p.actual == null ? "Awaiting box score" : `Finished with ${n(p.actual)}`;
  }
  if (!g.final) return "Awaiting final score";
  const margin = g.final.home - g.final.away;
  if (p.market === "total") return `Total ${g.final.home + g.final.away}`;
  const mine = p.selection === "home" ? margin : -margin;
  return mine === 0 ? `${p.team} tied` : `${p.team} ${mine > 0 ? "won" : "lost"} by ${Math.abs(mine)}`;
}

/** What the model's own number was, as a short aside. */
export function modelText(p: PickRow): string | null {
  if (p.market === "moneyline") return p.model_prob != null ? `${Math.round(p.model_prob * 100)}% to win` : null;
  if (p.model_number == null) return null;
  if (p.market === "spread") {
    const m = p.selection === "home" ? p.model_number : -p.model_number; // the selected team's projected margin
    return m === 0 ? "projected a tie" : `projected ${m > 0 ? "to win" : "to lose"} by ${n(Math.abs(m))}`;
  }
  if (p.market === "total") return `projected ${n(p.model_number)}`;
  return `projected ${formatProjection(p.model_number)}`; // player projections: whole numbers
}

export const RESULT_LABEL: Record<PickRow["result"], string> = { hit: "HIT", miss: "MISS", push: "PUSH", void: "VOID", cancelled: "CANCELLED", pending: "PENDING" };

/** "67–24" plus pushes when there are any. */
export function recordText(r: PickRecord): string {
  return `${r.hit}–${r.miss}${r.push ? `–${r.push}` : ""}`;
}

export const rateText = (r: PickRecord) => (r.hit_rate == null ? "–" : `${(r.hit_rate * 100).toFixed(1)}%`);

/** Tally a list of stored results the same way the published summary does: pushes graded, not in the rate. */
export function tally(results: PickRow["result"][]): PickRecord {
  const c = { hit: 0, miss: 0, push: 0, void: 0, cancelled: 0, pending: 0 };
  for (const r of results) c[r] += 1;
  const decided = c.hit + c.miss;
  return { ...c, graded: decided + c.push, hit_rate: decided ? c.hit / decided : null };
}

/** How a stored pick came to exist. Only a pick written before its game started counts as recorded pre-game. */
export type Provenance = "pre_game" | "reconstructed";
export const provenanceOf = (p: PickRow): Provenance => (p.frozen_before_start ? "pre_game" : "reconstructed");

/** Both teams' recorded win probabilities, from the stored winner pick. */
export function winProbs(p: PickRow): { home: number; away: number } | null {
  if (p.market !== "moneyline" || p.model_prob == null) return null;
  const mine = p.model_prob;
  return p.selection === "home" ? { home: mine, away: 1 - mine } : { home: 1 - mine, away: mine };
}

/** Actual minus projected, signed: 118 projected and 121 scored is "+3". A projection error, never a grade. */
export function scoreDiff(projected: number, actual: number): string {
  const d = Math.round((actual - projected) * 10) / 10;
  return d === 0 ? "0" : signed(d);
}

/** "BOS by 22", or "Tied". `margin` is home minus away. */
export function marginText(g: { home: string; away: string }, margin: number): string {
  const m = Math.round(margin * 10) / 10;
  return m === 0 ? "Tied" : `${m > 0 ? g.home : g.away} by ${n(Math.abs(m))}`;
}

export type GameStatus = "Final" | "Live" | "Upcoming" | "Not played" | "Awaiting final";

/** Final only when a verified final score is stored. Live is a started game inside a normal game's length. */
export function gameStatus(g: { status: string; start_time: string | null; final: Final }, nowMs: number): GameStatus {
  if (/postpon|cancel/i.test(g.status)) return "Not played";
  if (g.final) return "Final";
  const start = g.start_time ? Date.parse(g.start_time) : NaN;
  if (!Number.isFinite(start)) return "Awaiting final";
  if (nowMs < start) return "Upcoming";
  return nowMs - start < 4 * 3600_000 ? "Live" : "Awaiting final";
}

export const num = n;
