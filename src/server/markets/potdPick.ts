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
  /** Polymarket "N+" contract: Yes = over N - 0.5, No = under N - 0.5 */
  contract: number; side: "over" | "under"; line: number; price: number; modelProb: number; marketProb: number;
  edge: number; projection: number; difference: number; modelVersion: string;
}

const PT_DAY = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });

/** Games on the board that start later today (Pacific). */
export function todaysGameIds(board: EnginePropsBoard, now: Date): Set<string> {
  const today = PT_DAY(now);
  return new Set(board.games.filter((g) => g.start_time && Date.parse(g.start_time) > now.getTime() && PT_DAY(new Date(g.start_time)) === today).map((g) => g.game_id));
}

/** The highest-edge usable Polymarket quote among eligible stats, or null when nothing clears the bar. Never estimates a line. */
export function strongestLiveProp(league: League, board: EnginePropsBoard, ids: Set<string>): { pick: LivePropPick | null; checked: number } {
  let best: LivePropPick | null = null;
  let checked = 0;
  for (const g of board.games) {
    if (!ids.has(g.game_id)) continue;
    for (const p of g.players) {
      for (const stat of ELIGIBLE[league]) {
        const m = p.markets[stat];
        if (!m) continue;
        for (const t of m.thresholds) {
          if (t.op !== ">=" || t.variant) continue;
          const q = t.quotes.find((v) => v.provider === "polymarket_us" && v.usable);
          if (!q) continue;
          checked++;
          const sides: ["over" | "under", number, number | null][] = [["over", t.model_prob, q.yes_ask], ["under", 1 - t.model_prob, q.no_ask]];
          for (const [side, prob, price] of sides) {
            if (price === null) continue;
            const edge = prob - price;
            if (prob < MIN_PROB || edge < MIN_EDGE) continue;
            if (best && (edge < best.edge || (edge === best.edge && prob <= best.modelProb))) continue;
            best = {
              gameId: g.game_id, player: p.name, team: p.team, matchup: `${g.away.abbr} @ ${g.home.abbr}`, start: g.start_time, stat, label: m.label,
              contract: t.threshold, side, line: t.threshold - 0.5, price, modelProb: Math.round(prob * 1000) / 1000,
              marketProb: price, edge: Math.round(edge * 1000) / 1000, projection: Math.round(m.mean * 10) / 10,
              difference: Math.round((m.mean - (t.threshold - 0.5)) * 10) / 10, modelVersion: board.model.version,
            };
          }
        }
      }
    }
  }
  return { pick: best, checked };
}
