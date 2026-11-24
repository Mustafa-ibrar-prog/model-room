import { describe, expect, it } from "vitest";
import { mainConcern } from "@/lib/potdConcern";
import type { LivePropPick } from "@/server/markets/potdPick";

const base = {
  player: "A", team: "DEN", opp: "BOS", side: "over", line: 24.5, contract: 25, toward: 0, modelVersion: "0.2.0",
  history: { thisSeason: null, lastSeason: null }, form: { seasonAvg: 26, seasonGames: 12, last5: 27, last10: 26, last15: 26, range: { lo: 21, hi: 30, games: 18 } },
  injuries: { source: "NBA official injury report", reportTime: null, team: [], opp: [] }, game: null,
} as unknown as LivePropPick;

describe("Pick of the Day main concern", () => {
  it("names the most important thing, in order, and calls report items context", () => {
    expect(mainConcern({ ...base, injuries: { ...base.injuries!, team: [{ name: "A", status: "Questionable" }] } })).toBe("he is listed questionable on the injury report");
    expect(mainConcern({ ...base, injuries: { ...base.injuries!, team: [{ name: "B", status: "Out" }] } })).toBe("B listed out; model 0.2.0 doesn't read the injury report");
    expect(mainConcern({ ...base, toward: 0.18 })).toBe("18% of the projection comes from adjustments toward this side");
    expect(mainConcern({ ...base, game: { p15: 0.41 } as LivePropPick["game"] })).toContain("41% chance either team wins by 15+");
    expect(mainConcern({ ...base, history: { thisSeason: { hits: 4, games: 12 }, lastSeason: null } })).toBe("he has reached 25+ in only 4 of 12 games this season");
    expect(mainConcern({ ...base, line: 31.5 })).toContain("outside his typical range (21.0–30.0)");
    expect(mainConcern(base)).toBe("none flagged");
  });
  it("Questionable teammates are not called out (only Out / Doubtful)", () => {
    expect(mainConcern({ ...base, injuries: { ...base.injuries!, team: [{ name: "B", status: "Questionable" }] } })).toBe("none flagged");
  });
});
