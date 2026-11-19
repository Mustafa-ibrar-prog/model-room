import { describe, expect, it } from "vitest";
import { strongestLiveProp, todaysGameIds } from "@/server/markets/potdPick";
import type { EnginePropsBoard } from "@/types/props";

const q = (yes: number | null, no: number | null, usable = true) => ({
  provider: "polymarket_us", yes_bid: null, yes_ask: yes, no_ask: no, mid: null, spread: null, ask_size: null, fee_yes: 0, fee_no: 0,
  ev_yes: null, ev_no: null, captured_at: "2026-11-22T18:00:00Z", usable, flags: [],
});
const th = (k: number, p: number, quotes: ReturnType<typeof q>[]) => ({ op: ">=" as const, threshold: k, variant: null, model_prob: p, model_prob_raw: p, quotes, best: null, edge_grade: { grade: null, reasons: [] } });

function board(start: string): EnginePropsBoard {
  const mk = (label: string, mean: number, thresholds: ReturnType<typeof th>[]) => ({ label, mean, median: mean, sd: 5, support: "ok" as const, support_note: "", range_80: [0, 0] as [number, number], thresholds });
  return {
    model: { version: "0.2.0" },
    games: [{ game_id: "G1", start_time: start, game_date: "2026-11-22", week: 1, home: { abbr: "DEN", name: "" }, away: { abbr: "BOS", name: "" },
      players: [{ player_id: "1", name: "A", team: "DEN", markets: {
        points: mk("Points", 27.4, [th(25, 0.66, [q(0.55, 0.47)]), th(30, 0.30, [q(0.33, 0.69)])]),
        rebounds: mk("Rebounds", 9, [th(10, 0.45, [q(0.4, 0.62, false)])]),
        blocks: mk("Blocks", 2, [th(1, 0.95, [q(0.5, 0.52)])]),
      } }] }],
  } as unknown as EnginePropsBoard;
}

describe("Pick of the Day live preview", () => {
  const now = new Date("2026-11-22T20:00:00Z");
  it("picks the highest-edge usable eligible quote and never estimates a line", () => {
    const b = board("2026-11-23T02:00:00Z");
    const { pick, checked } = strongestLiveProp("nba", b, todaysGameIds(b, now));
    expect(checked).toBe(2);                                  // the unusable quote and the ineligible stat are skipped
    expect(pick?.stat).toBe("points");
    expect(pick?.side).toBe("over");                          // 66% vs 55c: 11 points
    expect(pick?.line).toBe(24.5);
    expect(pick?.contract).toBe(25);
    expect(pick?.edge).toBeCloseTo(0.11, 3);
  });
  it("returns nothing when no quote clears the bar or the game isn't today", () => {
    const b = board("2026-11-23T02:00:00Z");
    b.games[0].players[0].markets.points.thresholds = [th(25, 0.58, [q(0.56, 0.46)])];
    expect(strongestLiveProp("nba", b, todaysGameIds(b, now)).pick).toBeNull();
    expect(todaysGameIds(board("2026-11-24T02:00:00Z"), now).size).toBe(0);
    expect(todaysGameIds(board("2026-11-22T19:00:00Z"), now).size).toBe(0);  // already started
  });
});
