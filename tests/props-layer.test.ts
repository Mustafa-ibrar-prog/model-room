/**
 * Player-prop data layer: Free gets no player data, Plus gets projections and markets, Pro adds model inputs.
 * The board below is a SYNTHETIC fixture in the engine's schema; it exists only inside this test.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getProps } from "@/server/data/props";
import { isLocked } from "@/types/domain";

const quote = (usable: boolean, flags: string[] = []) => ({
  provider: "polymarket_us", yes_bid: 0.41, yes_ask: 0.43, no_ask: 0.59, mid: 0.42, spread: 0.02, ask_size: null,
  fee_yes: 0.017, fee_no: 0.017, ev_yes: 0.08, ev_no: -0.16, captured_at: "2030-01-01T12:00:00+00:00", usable, flags,
});

const player = (id: string, name: string) => ({
  player_id: id, name, team: "HOM", opp: "AWY", position: "WR", game_id: "g1", injury_status: null,
  inputs: { target_share: 0.271, coverage_factor: 1.04 },
  markets: {
    receiving_yards: {
      label: "Receiving yards", mean: 71.3, median: 66.0, sd: 35.1, support: "ok", support_note: "12 games, 95 targets", range_80: [28, 121],
      thresholds: [
        { op: ">=", threshold: 60, variant: null, model_prob: 0.537, model_prob_raw: 0.53, quotes: [quote(true)],
          best: { yes: { provider: "polymarket_us", price: 0.43, fee: 0.017, ev: 0.0903 }, no: null, edge: "yes" },
          edge_grade: { grade: "lean", reasons: ["size at this price not published"] } },
        { op: ">=", threshold: 80, variant: null, model_prob: 0.391, model_prob_raw: 0.39, quotes: [quote(false, ["stale"])], best: { yes: null, no: null, edge: null }, edge_grade: { grade: null, reasons: [] } },
      ],
    },
  },
});

const board = {
  schema_version: 1, league: "nfl", kind: "player_props", generated_at: "2030-01-01T12:00:00+00:00", season: 2030, week: 9,
  model: { id: "nfl-props", version: "9.9.9", status: "provisional", fitted_at: null, sims: 100 },
  data: { last_ingest: null, results_through: null, markets: [], markets_not_published: [{ provider: "kalshi", reason: "local only" }],
          comparison_rules: { max_age_min: 20, max_spread: 0.06, min_size: 50, min_ev: 0.02 } },
  performance: { backtest: null },
  games: [
    { game_id: "g1", start_time: "2030-01-02T00:30:00+00:00", game_date: "2030-01-01", week: 9,
      home: { abbr: "HOM", name: "Home Club" }, away: { abbr: "AWY", name: "Away Club" }, players: [player("p1", "Wide Out")] },
    { game_id: "g2", start_time: "2030-01-03T00:30:00+00:00", game_date: "2030-01-02", week: 9,
      home: { abbr: "AAA", name: "A" }, away: { abbr: "BBB", name: "B" }, players: [player("p2", "Second Game Guy")] },
  ],
};

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "mr-props-"));
  process.env.MODELROOM_PUBLISHED_DIR = dir;
});
afterEach(() => {
  delete process.env.MODELROOM_PUBLISHED_DIR;
});
const write = (b: unknown) => writeFileSync(path.join(dir, "nfl_props.json"), JSON.stringify(b));

describe("player props", () => {
  it("is unavailable, not invented, when no prop board exists", async () => {
    const res = await getProps("nfl", "pro");
    expect(res.ok).toBe(false);
  });

  it("sends Free no player data at all", async () => {
    write(board);
    const res = await getProps("nfl", "free");
    if (!res.ok) throw new Error("expected board");
    expect(isLocked(res.game)).toBe(true);
    const json = JSON.stringify(res);
    expect(json).not.toContain("Wide Out");
    expect(json).not.toContain("0.537");
    expect(res.gameCount).toBe(2);
  });

  it("gives Plus projections and usable market edges, but not model inputs", async () => {
    write(board);
    const res = await getProps("nfl", "plus");
    if (!res.ok || isLocked(res.game) || !res.game) throw new Error("expected game");
    const m = res.game.players[0].markets[0];
    expect(m.lines[0].edge).toMatchObject({ side: "yes", provider: "polymarket_us", price: 0.43, ev: 0.0903, grade: "lean", reasons: ["size at this price not published"] });
    expect(m.lines[1].market).toBeNull();          // stale quote is shown as unusable, never used
    expect(m.lines[1].quotes[0].flags).toContain("stale");
    expect(isLocked(res.game.players[0].inputs)).toBe(true);
    expect(JSON.stringify(res)).not.toContain("Second Game Guy"); // only the selected game is sent
  });

  it("gives Pro model inputs and honours the selected game", async () => {
    write(board);
    const res = await getProps("nfl", "pro", "g2");
    if (!res.ok || isLocked(res.game) || !res.game) throw new Error("expected game");
    expect(res.game.id).toBe("g2");
    expect(isLocked(res.game.players[0].inputs)).toBe(false);
  });
});
