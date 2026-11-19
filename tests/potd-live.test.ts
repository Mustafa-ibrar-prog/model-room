import { describe, expect, it } from "vitest";
import { inGrid, pmFee, strongestLiveProp, todaysGameIds } from "@/server/markets/potdPick";
import type { EnginePropsBoard } from "@/types/props";

const THETA = 0.0695;
const q = (yes: number | null, no: number | null, usable = true, fee: number | null = THETA) => ({
  provider: "polymarket_us", yes_bid: null, yes_ask: yes, no_ask: no, mid: null, spread: null, ask_size: null, fee_yes: 0, fee_no: 0,
  fee_coef: fee, ev_yes: null, ev_no: null, captured_at: "2026-11-22T18:00:00Z", usable, flags: [],
});
const th = (k: number, p: number, quotes: ReturnType<typeof q>[]) => ({ op: ">=" as const, threshold: k, variant: null, model_prob: p, model_prob_raw: p, quotes, best: null, edge_grade: { grade: null, reasons: [] } });
const grid = (n: number) => ({ k0: 0, step: 1, p: Array.from({ length: n }, (_, i) => Math.max(0, 1 - i / n)) });

function board(start: string, points: ReturnType<typeof th>[], gridLen = 41): EnginePropsBoard {
  const mk = (label: string, mean: number, thresholds: ReturnType<typeof th>[], g = grid(gridLen)) => ({ label, mean, median: mean, sd: 5, support: "ok" as const, support_note: "", range_80: [0, 0] as [number, number], thresholds, grid: g });
  return {
    model: { version: "0.2.0" },
    games: [{ game_id: "G1", start_time: start, game_date: "2026-11-22", week: 1, home: { abbr: "DEN", name: "" }, away: { abbr: "BOS", name: "" },
      players: [{ player_id: "1", name: "A", team: "DEN", markets: {
        points: mk("Points", 27.4, points),
        rebounds: mk("Rebounds", 9, [th(10, 0.45, [q(0.4, 0.62, false)])]),
        blocks: mk("Blocks", 2, [th(1, 0.95, [q(0.5, 0.52)])]),
      } }] }],
  } as unknown as EnginePropsBoard;
}

const now = new Date("2026-11-22T20:00:00Z");
const TONIGHT = "2026-11-23T02:00:00Z";
const run = (b: EnginePropsBoard) => strongestLiveProp("nba", b, todaysGameIds(b, now));

describe("Pick of the Day live preview", () => {
  it("picks the highest after-fee edge among usable eligible quotes", () => {
    const { pick, checked } = run(board(TONIGHT, [th(25, 0.66, [q(0.55, 0.47)]), th(30, 0.30, [q(0.33, 0.69)])]));
    expect(checked).toBe(2);                                  // the unusable quote and the ineligible stat are skipped
    expect(pick?.side).toBe("over");
    expect(pick?.line).toBe(24.5);
    expect(pick?.contract).toBe(25);
    expect(pick?.fee).toBeCloseTo(pmFee(THETA, 0.55), 3);    // 0.0695 * 0.55 * 0.45 = 0.0172
    expect(pick?.edge).toBeCloseTo(0.66 - 0.55 - pmFee(THETA, 0.55), 3);
  });

  it("fee math: θ·p·(1−p), largest at 50¢", () => {
    expect(pmFee(THETA, 0.5)).toBeCloseTo(0.017375, 6);
    expect(pmFee(THETA, 0.9)).toBeCloseTo(0.006255, 6);
    expect(pmFee(THETA, 0)).toBe(0);
  });

  it("a pick that qualifies before fees but not after is rejected", () => {
    // 0.60 model vs 0.555 ask: 4.5 points before fees, 0.60 - 0.555 - 0.0172 = 2.8 points after
    const b = board(TONIGHT, [th(25, 0.6, [q(0.555, 0.47)])]);
    expect(0.6 - 0.555).toBeGreaterThanOrEqual(0.04);
    expect(run(b).pick).toBeNull();
    expect(run(b).checked).toBe(1);
  });

  it("an unknown fee is never assumed to be zero", () => {
    expect(run(board(TONIGHT, [th(25, 0.8, [q(0.55, 0.47, true, null)])])).pick).toBeNull();
  });

  it("lines outside the model's grid are skipped, never clamped", () => {
    // grid covers 0..20: a 25+ line would have been priced from the grid's last point
    const out = run(board(TONIGHT, [th(25, 0.9, [q(0.3, 0.72)])], 21));
    expect(out.pick).toBeNull();
    expect(out.checked).toBe(0);
    expect(inGrid(grid(21), 20)).toBe(true);
    expect(inGrid(grid(21), 21)).toBe(false);
    expect(inGrid(grid(21), -1)).toBe(false);
    expect(inGrid(grid(21), 10.5)).toBe(false);              // between grid points: not the model's own number
    expect(inGrid(undefined, 5)).toBe(false);
  });

  it("returns nothing when no quote clears the bar or the game isn't today", () => {
    expect(run(board(TONIGHT, [th(25, 0.58, [q(0.56, 0.46)])])).pick).toBeNull();
    expect(todaysGameIds(board("2026-11-24T02:00:00Z", []), now).size).toBe(0);
    expect(todaysGameIds(board("2026-11-22T19:00:00Z", []), now).size).toBe(0);  // already started
  });
});
