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
  return `projected ${n(p.model_number)}`;
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
