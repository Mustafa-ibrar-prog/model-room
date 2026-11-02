/**
 * Website data layer: reads engine boards, gates premium fields, and shows
 * clear unavailable states. The board below is a SYNTHETIC fixture in the
 * engines' schema; it exists only inside this test.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getInjuries, getLeagueBoard, getRatings } from "@/server/data";
import { isLocked } from "@/types/domain";

function game(id: string, withMarket: boolean, final = false) {
  return {
    game_id: id, start_time: "2030-01-02T00:30:00+00:00", game_date: "2030-01-01", status: final ? "final" : "scheduled",
    neutral: false, week: 9,
    home: { id: "HOM", abbr: "HOM", name: "Home Club" }, away: { id: "AWY", abbr: "AWY", name: "Away Club" },
    rest: { home_days: 7, away_days: 7 },
    adjustments: { rest_points: 0, injury_points: null, qb_points: -1.5 },
    quarterbacks: { home: "Q Home", away: "Q Away" },
    projection: { home_score: 24, away_score: 20, margin: 4, total: 44, spread: -4, home_win_prob: 0.62, away_win_prob: 0.38,
                  margin_range_80: [-12, 20], total_range_80: [30, 58] },
    market: withMarket ? { spread: -2.5, total: 46.5, home_ml: -140, away_ml: 120, books: 0, captured_at: null, sources: ["nflverse"] } : null,
    edges: withMarket ? { spread: 1.5, total: -2.5, home_prob_market: 0.565, away_prob_market: 0.435, home_prob_diff: 0.055 } : null,
    result: final ? { home_score: 27, away_score: 17, margin: 10, total: 44 } : null,
  };
}

const board = {
  schema_version: 1, league: "nfl", generated_at: "2030-01-01T12:00:00+00:00", season: 2030, season_label: "2030", week: 9,
  model: { id: "nfl-game", version: "9.9.9", params_hash: "p", status: "provisional", fitted_at: null, inputs_hash: "i",
           uncertainty: { margin_sigma: 13, total_sigma: 13, method: "test" } },
  data: { sources: ["test"], freshness: { status: "current", reasons: [], results_through: "2029-12-31", last_ingest: null },
          injuries: { connected: true, note: null }, market: { connected: true, sources: ["nflverse"], note: null } },
  upcoming: [game("u1", true), game("u2", true), game("u3", true), game("u4", false)],
  recent: [game("r1", true, true)],
  ratings: [{ rank: 1, team_id: "HOM", abbr: "HOM", name: "Home Club", games_played: 8, overall: 3.2, overall_unit: "net pts / game",
              avg_margin: 4.1, last10_margin: 4.1, components: [{ key: "off", label: "Off", value: 0.1, unit: "EPA", higher_is_better: true }] }],
  injuries: [{ team: "HOM", player: "P One", position: "WR", status: "Out", injury: "Knee", practice: null, week: 9, impact_points: null, impact_note: "n/a" }],
  performance: { backtest: null, season_to_date: null, ledger: { tracked: 0, graded: 0 } },
};

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "mr-"));
  process.env.MODELROOM_PUBLISHED_DIR = dir;
});
afterEach(() => {
  delete process.env.MODELROOM_PUBLISHED_DIR;
});
const write = (b: unknown, league = "nfl") => writeFileSync(path.join(dir, `${league}.json`), JSON.stringify(b));

describe("engine boards", () => {
  it("reports unavailable (never demo data) when no board exists", async () => {
    const res = await getLeagueBoard("nba", "pro");
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.reason).toMatch(/python -m modelroom nba project/);
      expect(res.freshness.status).toBe("unavailable");
    }
  });

  it("rejects an unknown schema version", async () => {
    write({ ...board, schema_version: 2 });
    const res = await getLeagueBoard("nfl", "pro");
    expect(res.ok).toBe(false);
  });

  it("gives Free the model line and total but locks scores, probabilities and later edges", async () => {
    write(board);
    const res = await getLeagueBoard("nfl", "free");
    if (!res.ok) throw new Error("expected board");
    const [g1, g2, g3, g4] = res.upcoming;
    expect(g1.modelSpread).toBe(-4);
    expect(g1.modelTotal).toBe(44);
    expect(isLocked(g1.projectedScore)).toBe(true);
    expect(isLocked(g1.winProbability)).toBe(true);
    expect(g1.spreadEdge).toBe(1.5);           // first two games with a market line
    expect(g2.spreadEdge).toBe(1.5);
    expect(isLocked(g3.spreadEdge)).toBe(true); // third is Plus
    expect(g4.market).toBeNull();               // no line stays missing
    expect(isLocked(res.recentPregame)).toBe(true);
    expect(JSON.stringify(res)).not.toContain("0.62"); // locked win probability never leaves the server
  });

  it("gives Pro everything, with missing values kept as null", async () => {
    write(board);
    const res = await getLeagueBoard("nfl", "pro");
    if (!res.ok) throw new Error("expected board");
    const g4 = res.upcoming[3];
    expect(g4.projectedScore).toEqual({ home: 24, away: 20 });
    expect(g4.winProbability).toEqual({ home: 0.62, away: 0.38 });
    expect(g4.spreadEdge).toBeNull();
    expect(g4.injuryAdjustment).toBeNull();
    expect(res.upcoming[0].probabilityEdge).toEqual({ homeMarket: 0.565, homeDiff: 0.055 });
    expect(isLocked(res.recentPregame)).toBe(false);
  });

  it("gates rating breakdowns and injury impact", async () => {
    write(board);
    const free = await getRatings("nfl", "free");
    const pro = await getRatings("nfl", "pro");
    if (!free.ok || !pro.ok) throw new Error("expected ratings");
    expect(free.rows[0].overall).toBe(3.2);
    expect(isLocked(free.rows[0].components)).toBe(true);
    expect(isLocked(pro.rows[0].components)).toBe(false);
    const inj = await getInjuries("nfl", "free");
    if (!inj.ok) throw new Error("expected injuries");
    expect(inj.rows[0].status).toBe("Out");
    expect(isLocked(inj.rows[0].impactPoints)).toBe(true);
  });
});
