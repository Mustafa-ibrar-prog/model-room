import { describe, expect, it } from "vitest";
import { dayList, filterPicks, projectedVsActual, record, shiftDate, type HistFile, type HistPick } from "@/lib/potdHistory";

const p = (key: string, result: HistPick["result"], extra: Partial<HistPick> = {}): HistPick => ({
  pick_key: key, date: "2026-11-21", league: "nba", player: "A", player_id: "1", stat: "points", selection: "over", line: 20.5,
  projection: 23, model_version: "0.2.0", result, ...extra,
});
const picks = [p("1", "win"), p("2", "loss", { date: "2026-11-22", player: "B", stat: "assists" }), p("3", "push"), p("4", "void"), p("5", "pending", { model_version: "0.2.1" })];

describe("results dashboard record", () => {
  it("win rate is wins / (wins + losses); pushes, voids and pending excluded", () => {
    const r = record(picks);
    expect([r.win, r.loss, r.push, r.void, r.pending, r.settled, r.total]).toEqual([1, 1, 1, 1, 1, 2, 5]);
    expect(r.winRate).toBe(0.5);
    expect(record([]).winRate).toBeNull();
  });
  it("filters change the list, never the all-time record", () => {
    const shown = filterPicks(picks, { result: "loss" });
    expect(shown.map((x) => x.pick_key)).toEqual(["2"]);
    expect(record(picks).settled).toBe(2);
    expect(filterPicks(picks, { stat: "assists" }).length).toBe(1);
    expect(filterPicks(picks, { version: "0.2.1" }).map((x) => x.pick_key)).toEqual(["5"]);
    expect(filterPicks(picks, { from: "2026-11-22", to: "2026-11-22" }).map((x) => x.pick_key)).toEqual(["2"]);
    expect(filterPicks(picks, { player: "B" }).length).toBe(1);
  });
  it("projected vs actual comes from the stored projection and the graded stat only", () => {
    expect(projectedVsActual(p("x", "loss", { grade: { actual: 18 } }))).toEqual({ projected: 23, actual: 18, missBy: -2.5 });
    expect(projectedVsActual(p("y", "pending")).actual).toBeNull();
    expect(projectedVsActual(p("z", "win", { selection: "under", grade: { actual: 18 } })).missBy).toBe(2.5);
  });
  it("day navigation covers today and every recorded day", () => {
    const f = { today: "2026-11-24", days: [{ date: "2026-11-19", picks: 0, reason: "r" }], picks: [p("1", "win")] } as unknown as HistFile;
    expect(dayList(f)).toEqual(["2026-11-24", "2026-11-21", "2026-11-19"]);
    expect(shiftDate("2026-11-01", -1)).toBe("2026-10-31");
  });
});
