/**
 * Market-settled results on the site: summaries for every plan, records for Pro only, filters, and the
 * statuses taken exactly as the settlement job wrote them. SYNTHETIC fixture, exists only in this test.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getMarketResults, getMarketResultsForDate } from "@/server/data/marketResults";
import { isLocked } from "@/types/domain";

const rec = (id: string, status: string, result: string | null, p: number, extra: Record<string, unknown> = {}) => ({
  id, league: "nfl", kind: "prop", game_id: "g1", game_start: "2030-01-05T18:00:00Z", game_date: "2030-01-05", provider: "kalshi",
  market_id: id, market: "receptions", market_label: "Receptions", op: ">=", threshold: 5, variant: null, team: "HOM", player: "P", player_id: "p1",
  model_version: "0.1.0", predicted_at: "2030-01-05T12:00:00Z", captured_at: null, model_prob: p, model_call: p > 0.5 ? "yes" : "no",
  market_bid: 0.4, market_ask: 0.44, market_implied: 0.42, edge: null, status,
  settlement: result ? { state: "settled", result, value: null, settled_at: null, settled_at_source: null, provider_status: "finalized", note: null, observed_at: "x", first_settled_at: "x" } : null,
  corrections: [], projection: null, actual: null, ...extra,
});

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "mr-results-"));
  process.env.MODELROOM_PUBLISHED_DIR = dir;
  writeFileSync(path.join(dir, "market_results_nfl.json"), JSON.stringify({
    league: "nfl", generated_at: "2030-01-06T00:00:00Z", note: "", providers: [], withheld: {},
    records: [
      rec("a", "won", "yes", 0.7), rec("b", "lost", "yes", 0.3), rec("c", "void", "void", 0.6), rec("d", "pending", null, 0.55),
      rec("e", "won", "no", 0.2, { game_date: "2030-02-01", provider: "polymarket_us", market: "points", market_label: "Points" }),
    ],
  }));
});
afterEach(() => {
  delete process.env.MODELROOM_PUBLISHED_DIR;
});

describe("market-settled results", () => {
  it("counts statuses as written and scores only settled yes/no markets", async () => {
    const v = await getMarketResults("nfl", "free", {});
    expect(v.overall).toMatchObject({ predictions: 5, settled: 4, won: 2, lost: 1, void: 1, pending: 1, n_scored: 3 });
    expect(v.overall.win_pct).toBeCloseTo(2 / 3);
    expect(v.overall.brier).toBeCloseTo(((0.7 - 1) ** 2 + (0.3 - 1) ** 2 + 0.2 ** 2) / 3);
  });

  it("keeps individual records (with prices) for Pro", async () => {
    expect(isLocked((await getMarketResults("nfl", "free", {})).records)).toBe(true);
    expect(isLocked((await getMarketResults("nfl", "plus", {})).records)).toBe(true);
    const pro = await getMarketResults("nfl", "pro", {});
    expect(!isLocked(pro.records) && pro.records.length).toBe(5);
    expect(isLocked(await getMarketResultsForDate("nfl", "2030-01-05", "plus"))).toBe(true);
  });

  it("filters by date range, provider, market and status; ignores bad input", async () => {
    expect((await getMarketResults("nfl", "pro", { from: "2030-01-10" })).overall.predictions).toBe(1);
    expect((await getMarketResults("nfl", "pro", { provider: "kalshi" })).overall.predictions).toBe(4);
    expect((await getMarketResults("nfl", "pro", { market: "points" })).overall.won).toBe(1);
    const s = await getMarketResults("nfl", "pro", { status: "pending" });
    expect(!isLocked(s.records) && s.records.map((r) => r.id)).toEqual(["d"]);
    const bad = await getMarketResults("nfl", "pro", { from: "../../etc", provider: "nope" });
    expect(bad.overall.predictions).toBe(5);
  });
});
