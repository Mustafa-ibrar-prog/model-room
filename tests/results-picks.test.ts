/** The results page words a stored pick and its outcome; it never decides a result itself. */
import { describe, expect, it } from "vitest";
import { gameStatus, marginText, modelText, outcomeText, pickText, provenanceOf, rateText, recordText, scoreDiff, tally, winProbs } from "@/components/results/picks";
import type { PickRow } from "@/types/history";

const p = (o: Partial<PickRow>): PickRow =>
  ({ id: "x", game_id: "g", market: "moneyline", selection: "home", team: "AAA", line: null, model_number: null, model_prob: null,
     model_version: "1", recorded_at: "", backfilled: false, result: "hit", ...o }) as PickRow;
const game = (home: number, away: number) => ({ home: "AAA", away: "BBB", final: { home, away } });

describe("pick and outcome wording", () => {
  it("spread: the selected team with its own line, and its margin", () => {
    const fav = p({ market: "spread", selection: "home", team: "AAA", line: -7.5, model_number: 9.4 });
    expect(pickText(fav)).toBe("AAA −7.5");
    expect(outcomeText(fav, game(122, 100))).toBe("AAA won by 22");
    expect(modelText(fav)).toBe("projected to win by 9.4");
    const dog = p({ market: "spread", selection: "away", team: "BBB", line: 7.5, model_number: 4 });
    expect(pickText(dog)).toBe("BBB +7.5");
    expect(outcomeText(dog, game(103, 100))).toBe("BBB lost by 3");
    expect(modelText(dog)).toBe("projected to lose by 4");
  });
  it("total, moneyline and props", () => {
    expect(pickText(p({ market: "total", selection: "under", line: 225.5 }))).toBe("Under 225.5");
    expect(outcomeText(p({ market: "total", selection: "under", line: 225.5 }), game(120, 110))).toBe("Total 230");
    expect(pickText(p({ market: "moneyline", team: "BBB", selection: "away" }))).toBe("BBB to win");
    expect(outcomeText(p({ market: "moneyline", team: "BBB", selection: "away" }), game(100, 110))).toBe("BBB won by 10");
    expect(pickText(p({ market: "prop", selection: "at_least", line: 20, stat_label: "Points" }))).toBe("20+ points");
    expect(pickText(p({ market: "prop", selection: "below", line: 20, stat_label: "Points" }))).toBe("Under 20 points");
    expect(outcomeText(p({ market: "prop", selection: "at_least", line: 20, actual: 27 }), game(1, 0))).toBe("Finished with 27");
  });
  it("says so when there is nothing to grade yet, or the pick has no action", () => {
    expect(outcomeText(p({ result: "pending" }), { home: "AAA", away: "BBB", final: null })).toBe("Awaiting final score");
    expect(outcomeText(p({ market: "prop", result: "void", played: false }), game(1, 0))).toBe("Did not play");
    expect(outcomeText(p({ market: "prop", result: "pending", actual: null }), game(1, 0))).toBe("Awaiting box score");
    expect(outcomeText(p({ result: "cancelled" }), { home: "AAA", away: "BBB", final: null })).toBe("Game not played");
  });
});

describe("the record", () => {
  it("counts only settled picks: pending, void and cancelled never touch the rate", () => {
    const r = tally(["hit", "hit", "hit", "miss", "push", "void", "cancelled", "pending", "pending"]);
    expect([r.hit, r.miss, r.push, r.void, r.cancelled, r.pending, r.graded]).toEqual([3, 1, 1, 1, 1, 2, 5]);
    expect(r.hit_rate).toBe(0.75);
    expect(recordText(r)).toBe("3–1–1");
    expect(rateText(r)).toBe("75.0%");
    const none = tally(["pending", "void"]);
    expect(none.hit_rate).toBeNull();
    expect(rateText(none)).toBe("–");
  });
});

describe("the expanded game card", () => {
  it("shows both teams' recorded win probability", () => {
    expect(winProbs(p({ selection: "away", model_prob: 0.73 }))).toEqual({ home: 0.27, away: 0.73 });
    expect(winProbs(p({ selection: "home", model_prob: 0.6 }))).toEqual({ home: 0.6, away: 0.4 });
    expect(winProbs(p({ market: "spread", model_prob: null }))).toBeNull();
  });
  it("a projected score gets a signed difference, actual minus projected, and no grade", () => {
    expect(scoreDiff(118, 121)).toBe("+3");
    expect(scoreDiff(110, 99)).toBe("−11");
    expect(scoreDiff(104.1, 106)).toBe("+1.9");
    expect(scoreDiff(100, 100)).toBe("0");
    expect(marginText({ home: "AAA", away: "BBB" }, -8.11)).toBe("BBB by 8.1");
    expect(marginText({ home: "AAA", away: "BBB" }, 22)).toBe("AAA by 22");
    expect(marginText({ home: "AAA", away: "BBB" }, 0)).toBe("Tied");
  });
  it("only a pick written before the game started is labelled recorded pre-game", () => {
    expect(provenanceOf(p({ frozen_before_start: true }))).toBe("pre_game");
    expect(provenanceOf(p({ frozen_before_start: false, backfilled: true }))).toBe("reconstructed");
    expect(provenanceOf(p({ frozen_before_start: false, backfilled: false }))).toBe("reconstructed");
    expect(provenanceOf(p({}))).toBe("reconstructed"); // older rows without the flag are never promoted
  });
  it("status: Final needs a stored final score", () => {
    const start = "2026-11-14T00:00:00+00:00", t = Date.parse(start);
    expect(gameStatus({ status: "final", start_time: start, final: { home: 1, away: 0 } }, t + 9e6)).toBe("Final");
    expect(gameStatus({ status: "scheduled", start_time: start, final: null }, t - 1)).toBe("Upcoming");
    expect(gameStatus({ status: "scheduled", start_time: start, final: null }, t + 3600_000)).toBe("Live");
    expect(gameStatus({ status: "scheduled", start_time: start, final: null }, t + 6 * 3600_000)).toBe("Awaiting final");
    expect(gameStatus({ status: "postponed", start_time: start, final: null }, t + 1)).toBe("Not played");
  });
});
