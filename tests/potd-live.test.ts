import { describe, expect, it } from "vitest";
import { formatProjection } from "@/lib/format";
import { adjustedProb, ELIGIBLE, inGrid, liveReason, pmFee, RELIABILITY, strongestLiveProp, todaysGameIds, towardShare } from "@/server/markets/potdPick";
import type { EnginePropsBoard } from "@/types/props";

const THETA = 0.0695;
const q = (yes: number | null, no: number | null, usable = true, fee: number | null = THETA) => ({
  provider: "polymarket_us", yes_bid: null, yes_ask: yes, no_ask: no, mid: null, spread: null, ask_size: null, fee_yes: 0, fee_no: 0,
  fee_coef: fee, ev_yes: null, ev_no: null, captured_at: "2026-11-22T18:00:00Z", usable, flags: [],
});
const th = (k: number, p: number, quotes: ReturnType<typeof q>[]) => ({ op: ">=" as const, threshold: k, variant: null, model_prob: p, model_prob_raw: p, quotes, best: null, edge_grade: { grade: null, reasons: [] } });
const grid = (n: number) => ({ k0: 0, step: 1, p: Array.from({ length: n }, (_, i) => Math.max(0, 1 - i / n)) });
type Th = ReturnType<typeof th>;

function player(id: string, name: string, points: Th[], opts: { gridLen?: number; mean?: number; pts?: Record<string, number> } = {}) {
  const mk = (label: string, mean: number, thresholds: Th[], g = grid(opts.gridLen ?? 41)) => ({ label, mean, median: mean, sd: 5, support: "ok" as const, support_note: "200 games, 6000 minutes", range_80: [0, 0] as [number, number], thresholds, grid: g });
  return {
    player_id: id, name, team: "DEN", opp: "BOS", position: "C", game_id: "G1", injury_status: null,
    inputs: { teammates_out: "", opp_points_factor: 1.03, contributions: opts.pts ? { stats: { pts: opts.pts }, minutes: { usual: 30, projected: 31 } } : undefined },
    markets: {
      points: mk("Points", opts.mean ?? 27.4, points),
      rebounds: mk("Rebounds", 9, [th(10, 0.45, [q(0.4, 0.62, false)])]),
      blocks: mk("Blocks", 2, [th(1, 0.95, [q(0.5, 0.52)])]),
    },
  };
}

function board(start: string, players: ReturnType<typeof player>[], version = "0.2.0"): EnginePropsBoard {
  return {
    model: { version }, generated_at: "2026-11-22T17:00:00Z",
    games: [{ game_id: "G1", start_time: start, game_date: "2026-11-22", week: 1, home: { abbr: "DEN", name: "" }, away: { abbr: "BOS", name: "" }, players }],
  } as unknown as EnginePropsBoard;
}
const one = (start: string, points: Th[], gridLen = 41) => board(start, [player("1", "A", points, { gridLen })]);

const now = new Date("2026-11-22T20:00:00Z");
const TONIGHT = "2026-11-23T02:00:00Z";
const run = (b: EnginePropsBoard) => strongestLiveProp(b, todaysGameIds(b, now));

describe("NBA Pick of the Day live preview", () => {
  it("is NBA only: points, rebounds, assists, threes", () => {
    expect([...ELIGIBLE]).toEqual(["points", "rebounds", "assists", "threes"]);
    expect(RELIABILITY.model).toBe("0.2.0");
  });

  it("qualifies on the reliability-adjusted probability and reports the after-fee edge against it", () => {
    const { pick, checked } = run(one(TONIGHT, [th(25, 0.66, [q(0.55, 0.47)]), th(30, 0.30, [q(0.33, 0.69)])]));
    expect(checked).toBe(2);                                  // the unusable quote and the ineligible stat are skipped
    expect(pick?.side).toBe("over");
    expect(pick?.line).toBe(24.5);
    expect(pick?.contract).toBe(25);
    expect(pick?.modelProb).toBeCloseTo(0.66, 3);
    expect(pick?.adjProb).toBeCloseTo(adjustedProb(0.66, 0), 3);   // no contributions: toward = 0
    expect(pick?.adjProb).toBeLessThan(0.66);                       // raw model sides ran overconfident in the backtest
    expect(pick?.fee).toBeCloseTo(pmFee(THETA, 0.55), 3);
    expect(pick?.edge).toBeCloseTo(adjustedProb(0.66, 0) - 0.55 - pmFee(THETA, 0.55), 3);
    expect(pick?.modelVersion).toBe("0.2.0");
  });

  it("marks down a projection that rests on adjustments (the Wembanyama case) and says why it was rejected", () => {
    // baseline 24.4, blowout -2.9, matchup -0.4: 13% of the projection comes from adjustments toward the Under
    const pts = { baseline: 24.4, minutes: 0, blowout: -2.9, usage: 0, pace: -0.3, matchup: -0.36, simulation: 0, final: 20.84 };
    const b = board(TONIGHT, [player("9", "W", [th(25, 0.35, [q(0.49, 0.52)])], { mean: 20.84, pts })]);
    expect(towardShare(pts, "under")).toBeCloseTo(3.26 / 24.4, 3);
    const out = run(b);
    expect(out.pick).toBeNull();                              // raw 65% Under, but about 55.6% after the adjustment
    expect(out.diag.belowProb).toBe(1);
    expect(out.rejected[0].why).toContain("after the reliability adjustment");
    expect(out.rejected[0].modelProb).toBeCloseTo(0.65, 3);
  });

  it("ranks by adjusted probability, not by the biggest gap", () => {
    const steady = player("1", "Steady", [th(20, 0.74, [q(0.6, 0.42)])], { mean: 24 });        // 74% raw, smaller edge
    const gap = player("2", "Gap", [th(25, 0.69, [q(0.45, 0.57)])], { mean: 29 });              // 69% raw, bigger edge
    const { pick } = run(board(TONIGHT, [steady, gap]));
    expect(pick?.player).toBe("Steady");
    expect(adjustedProb(0.69, 0) - 0.45 - pmFee(THETA, 0.45)).toBeGreaterThan(adjustedProb(0.74, 0) - 0.6 - pmFee(THETA, 0.6));
  });

  it("keeps full precision internally; the projection displays as a whole number", () => {
    const { pick } = run(one(TONIGHT, [th(25, 0.66, [q(0.55, 0.47)])]));
    expect(pick?.projection).toBe(27.4);
    expect(pick?.difference).toBeCloseTo(2.9, 9);
    expect(formatProjection(pick!.projection)).toBe("27");
    expect(pick?.line).toBe(24.5);                            // market line never rounded
  });

  it("fee math: θ·p·(1−p), largest at 50¢", () => {
    expect(pmFee(THETA, 0.5)).toBeCloseTo(0.017375, 6);
    expect(pmFee(THETA, 0.9)).toBeCloseTo(0.006255, 6);
    expect(pmFee(THETA, 0)).toBe(0);
  });

  it("a pick that clears the probability bar but not the edge after fees is rejected", () => {
    const b = one(TONIGHT, [th(25, 0.6, [q(0.555, 0.47)])]);
    expect(run(b).pick).toBeNull();
    expect(run(b).checked).toBe(1);
    expect(run(b).rejected[0].why).toContain("edge after fees");
  });

  it("an unknown fee is never assumed to be zero", () => {
    expect(run(one(TONIGHT, [th(25, 0.8, [q(0.55, 0.47, true, null)])])).pick).toBeNull();
  });

  it("lines outside the model's grid are skipped, never clamped", () => {
    const out = run(one(TONIGHT, [th(25, 0.9, [q(0.3, 0.72)])], 21));
    expect(out.pick).toBeNull();
    expect(out.checked).toBe(0);
    expect(inGrid(grid(21), 20)).toBe(true);
    expect(inGrid(grid(21), 21)).toBe(false);
    expect(inGrid(grid(21), -1)).toBe(false);
    expect(inGrid(grid(21), 10.5)).toBe(false);
    expect(inGrid(undefined, 5)).toBe(false);
  });

  it("returns nothing when no quote clears the bar or the game isn't today", () => {
    expect(run(one(TONIGHT, [th(25, 0.58, [q(0.56, 0.46)])])).pick).toBeNull();
    expect(todaysGameIds(one("2026-11-24T02:00:00Z", []), now).size).toBe(0);
    expect(todaysGameIds(one("2026-11-22T19:00:00Z", []), now).size).toBe(0);  // already started
  });

  it("diagnostics count why each matched line was dropped", () => {
    const b = one(TONIGHT, [
      th(25, 0.6, [q(0.555, 0.47)]),              // passes the adjusted probability, fails the edge after fees
      th(20, 0.52, [q(0.5, 0.52)]),               // neither side reaches 56.5%
      th(45, 0.9, [q(0.3, 0.72)]),                // outside a 41-point grid
      th(30, 0.7, [q(0.4, 0.62, true, null)]),    // no fee
    ]);
    const { pick, diag } = run(b);
    expect(pick).toBeNull();
    expect(diag).toEqual({ quotes: 5, unusable: 1, outsideGrid: 1, noFee: 1, belowProb: 1, belowEdge: 1, checked: 2 });
    const why = liveReason({ games: 1, found: 1, matched: 5 }, diag);
    expect(why).toContain("5 Polymarket lines matched");
    expect(why).toContain("1 under a 4-point edge after fees");
    expect(why).toContain("1 outside the model's range");
  });

  it("reasons distinguish no listing, a failed fetch and no match", () => {
    const d0 = { quotes: 0, unusable: 0, outsideGrid: 0, noFee: 0, belowProb: 0, belowEdge: 0, checked: 0 };
    expect(liveReason({ games: 4, found: 0, matched: 0 }, d0)).toBe("Polymarket has no market listed for any of today's 4 games yet.");
    expect(liveReason({ games: 4, found: 0, matched: 0, errors: 4, errorCodes: [0, 503] }, d0)).toContain("didn't answer for 4 of 4 games (timeout, HTTP 503)");
    expect(liveReason({ games: 4, found: 3, matched: 0 }, d0)).toContain("no player-prop line matched");
    expect(liveReason({ games: 0, found: 0, matched: 0 }, d0)).toBe("No NBA games left today.");
  });
});
