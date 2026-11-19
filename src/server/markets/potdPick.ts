import type { League } from "@/types/domain";
import type { EnginePropsBoard } from "@/types/props";

/** Same bar as the recorded Pick of the Day (modeling/modelroom/potd.py). */
export const MIN_PROB = 0.565;
export const MIN_EDGE = 0.04;
export const ELIGIBLE: Record<League, string[]> = {
  nba: ["points", "rebounds", "assists", "threes"],
  nfl: ["passing_yards", "rushing_yards", "receiving_yards", "receptions", "anytime_td", "passing_tds"],
};

export interface LivePropPick {
  gameId: string; player: string; team: string; matchup: string; start: string | null; stat: string; label: string;
  /** Polymarket "at least N" contract: Yes = over N - 0.5, No = under N - 0.5 */
  contract: number; side: "over" | "under"; line: number;
  /** ask price of the chosen side, its trading fee, and price + fee (the cost the edge is measured against) */
  price: number; fee: number; cost: number;
  modelProb: number; marketProb: number;
  /** model probability minus cost (after fees) */
  edge: number; projection: number; difference: number; modelVersion: string;
}

/** Polymarket US trading fee per contract: θ·p·(1−p). */
export const pmFee = (theta: number, price: number) => theta * price * (1 - price);

/** True when line N sits inside the model's own probability grid, so P(stat >= N) is the model's number, not a clamp. */
export function inGrid(grid: { k0: number; step: number; p: number[] } | undefined, n: number): boolean {
  if (!grid || !grid.p.length) return false;
  const x = (n - grid.k0) / grid.step;
  return x >= 0 && x <= grid.p.length - 1 && Math.abs(x - Math.round(x)) < 1e-9;
}

const PT_DAY = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });

/** Games on the board that start later today (Pacific). */
export function todaysGameIds(board: EnginePropsBoard, now: Date): Set<string> {
  const today = PT_DAY(now);
  return new Set(board.games.filter((g) => g.start_time && Date.parse(g.start_time) > now.getTime() && PT_DAY(new Date(g.start_time)) === today).map((g) => g.game_id));
}

/** Why quotes were dropped, in the order the filters run. */
export interface LiveDiag {
  quotes: number; unusable: number; outsideGrid: number; noFee: number; belowProb: number; belowEdge: number; checked: number;
}

/** The highest after-fee-edge usable Polymarket quote among eligible stats, or null. Never estimates a line. */
export function strongestLiveProp(league: League, board: EnginePropsBoard, ids: Set<string>): { pick: LivePropPick | null; checked: number; diag: LiveDiag } {
  let best: LivePropPick | null = null;
  const d: LiveDiag = { quotes: 0, unusable: 0, outsideGrid: 0, noFee: 0, belowProb: 0, belowEdge: 0, checked: 0 };
  const r3 = (x: number) => Math.round(x * 1000) / 1000;
  for (const g of board.games) {
    if (!ids.has(g.game_id)) continue;
    for (const p of g.players) {
      for (const stat of ELIGIBLE[league]) {
        const m = p.markets[stat];
        if (!m) continue;
        for (const t of m.thresholds) {
          if (t.op !== ">=" || t.variant) continue;
          const all = t.quotes.filter((v) => v.provider === "polymarket_us");
          if (!all.length) continue;
          d.quotes++;
          const q = all.find((v) => v.usable);
          if (!q) { d.unusable++; continue; }                          // started, closed, one-sided, crossed or wide spread
          if (!inGrid(m.grid, t.threshold)) { d.outsideGrid++; continue; }   // never clamped or estimated
          if (q.fee_coef == null) { d.noFee++; continue; }            // fee unknown: never assumed free
          d.checked++;
          const sides: ["over" | "under", number, number | null][] = [["over", t.model_prob, q.yes_ask], ["under", 1 - t.model_prob, q.no_ask]];
          let probOk = false, edgeOk = false;
          for (const [side, prob, price] of sides) {
            if (price === null) continue;
            if (prob < MIN_PROB) continue;
            probOk = true;
            const fee = pmFee(q.fee_coef, price);
            const cost = price + fee;
            const edge = prob - cost;
            if (edge < MIN_EDGE) continue;
            edgeOk = true;
            if (best && (edge < best.edge || (edge === best.edge && prob <= best.modelProb))) continue;
            best = {
              gameId: g.game_id, player: p.name, team: p.team, matchup: `${g.away.abbr} @ ${g.home.abbr}`, start: g.start_time, stat, label: m.label,
              contract: t.threshold, side, line: t.threshold - 0.5, price, fee: r3(fee), cost: r3(cost), modelProb: r3(prob),
              marketProb: price, edge: r3(edge), projection: Math.round(m.mean * 10) / 10,
              difference: Math.round((m.mean - (t.threshold - 0.5)) * 10) / 10, modelVersion: board.model.version,
            };
          }
          if (!probOk) d.belowProb++;
          else if (!edgeOk) d.belowEdge++;
        }
      }
    }
  }
  return { pick: best, checked: d.checked, diag: d };
}

/** Plain-language reason for "no qualifying pick", from the fetch counts and the filter counts. */
export function liveReason(info: { games: number; found: number; matched: number; errors?: number; errorCodes?: number[] }, d: LiveDiag): string {
  if (!info.games) return "No games left today.";
  if (info.errors && !info.found) {
    const how = (info.errorCodes ?? []).map((c) => (c ? `HTTP ${c}` : "timeout")).join(", ");
    return `Polymarket didn't answer for ${info.errors} of ${info.games} games (${how}); nothing to compare yet.`;
  }
  if (!info.found) return `Polymarket has no market listed for any of today's ${info.games} games yet.`;
  if (!info.matched || !d.quotes) return `Polymarket lists ${info.found} of ${info.games} games, but no player-prop line matched a player and stat on the model's board.`;
  const parts = [`${d.quotes} Polymarket lines matched`];
  if (d.unusable) parts.push(`${d.unusable} not tradable now (closed, one-sided or spread too wide)`);
  if (d.outsideGrid) parts.push(`${d.outsideGrid} outside the model's range`);
  if (d.noFee) parts.push(`${d.noFee} without a published fee`);
  if (d.belowProb) parts.push(`${d.belowProb} where neither side reaches ${(MIN_PROB * 100).toFixed(1)}%`);
  if (d.belowEdge) parts.push(`${d.belowEdge} under a ${(MIN_EDGE * 100).toFixed(0)}-point edge after fees`);
  return parts.join("; ") + ".";
}
