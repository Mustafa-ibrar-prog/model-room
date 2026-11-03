/** Owner-only live Polymarket US view: parsing, pricing and merging. Uses the recorded fixture; no network. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bestOf, candidateSlugs, gridProb, normName, ownerLiveMarkets, parseGame, parseProps, quoteView, withLivePolymarket, type PmEvent,
} from "@/server/markets/polymarketLive";
import type { EnginePropsBoard } from "@/types/props";

const fixture = JSON.parse(readFileSync(path.join(__dirname, "../modeling/tests/markets/fixtures/polymarket_us_event_nba.json"), "utf8"));
const ev: PmEvent = fixture.event ?? fixture;

describe("polymarket live", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("builds slugs with Polymarket's team codes, both orders", () => {
    const s = candidateSlugs("nba", "GS", "NY", "2026-11-04");
    expect(s).toContain("nba-gsw-nyk-2026-11-04");
    expect(s).toContain("nba-nyk-gsw-2026-11-04");
  });

  it("parses player props from the fixture", () => {
    const ps = parseProps(ev);
    expect(ps.length).toBeGreaterThan(5);
    const p = ps.find((x) => x.player === "Donovan Mitchell" && x.market === "rebounds")!;
    expect(p).toMatchObject({ line: 2, bid: 0.57, ask: 0.67, status: "open" });
  });

  it("interpolates the probability grid and clamps outside it", () => {
    const g = { k0: 100, step: 5, p: [0.9, 0.8, 0.6] };
    expect(gridProb(g, 100)).toBe(0.9);
    expect(gridProb(g, 107)).toBeCloseTo(0.72, 6);
    expect(gridProb(g, 50)).toBe(0.9);
    expect(gridProb(g, 500)).toBe(0.6);
  });

  it("flags wide and one-sided quotes and computes EV after fee", () => {
    const v = quoteView({ bid: 0.4, ask: 0.42, fee: 0.07, status: "open", slug: "x" }, 0.55, "t", false);
    expect(v.usable).toBe(true);
    expect(v.ev_yes).toBeCloseTo(0.55 - 0.42 - 0.07 * 0.42 * 0.58, 4);
    expect(quoteView({ bid: 0.3, ask: 0.45, fee: 0, status: "open", slug: "x" }, 0.5, "t", false).flags).toContain("wide spread");
    expect(quoteView({ bid: null, ask: 0.45, fee: 0, status: "open", slug: "x" }, 0.5, "t", false).flags).toContain("one-sided");
    expect(bestOf([v])?.edge).toBe("yes");
  });

  it("finds the main game lines (home-team spread, over total, home win)", () => {
    const g: PmEvent = {
      markets: [
        { marketType: "spreads", sportsMarketType: "basketball_full_game_spread", line: -8.5, bestBidQuote: { value: "0.49" }, bestAskQuote: { value: "0.51" }, status: "MARKET_STATUS_OPEN", marketSides: [{ long: true, team: { abbreviation: "det" } }] },
        { marketType: "spreads", sportsMarketType: "basketball_full_game_spread", line: -12.5, bestBidQuote: { value: "0.30" }, bestAskQuote: { value: "0.32" }, status: "MARKET_STATUS_OPEN", marketSides: [{ long: true, team: { abbreviation: "det" } }] },
        { marketType: "totals", sportsMarketType: "basketball_full_game_total", line: 221.5, bestBidQuote: { value: "0.50" }, bestAskQuote: { value: "0.52" }, status: "MARKET_STATUS_OPEN", marketSides: [{ long: true, description: "Over 221.5" }] },
        { marketType: "totals", sportsMarketType: "basketball_first_half_total", line: 110.5, bestBidQuote: { value: "0.50" }, bestAskQuote: { value: "0.51" }, status: "MARKET_STATUS_OPEN", marketSides: [{ long: true, description: "Over 110.5" }] },
        { marketType: "moneyline", sportsMarketType: "moneyline", bestBidQuote: { value: "0.20" }, bestAskQuote: { value: "0.22" }, status: "MARKET_STATUS_OPEN", marketSides: [{ long: true, team: { abbreviation: "phi" } }] },
      ],
    };
    const l = parseGame("nba", g, { abbr: "DET", name: "Detroit Pistons" }, { abbr: "PHI", name: "Philadelphia 76ers" });
    expect(l.spread).toEqual({ home: -8.5, mid: 0.5 });
    expect(l.total?.line).toBe(221.5);
    expect(l.homeWin).toBeCloseTo(0.79, 6);
  });

  it("is off for logged-out viewers and in production", async () => {
    expect(await ownerLiveMarkets()).toBe(false);
    vi.stubEnv("VERCEL_ENV", "production");
    expect(await ownerLiveMarkets()).toBe(false);
  });

  it("merges live quotes, adding lines the board doesn't list from the grid", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url.endsWith("nba-cle-okc-2030-01-01") ? new Response(JSON.stringify({ event: ev }), { status: 200 }) : new Response("", { status: 404 })));
    const board = {
      games: [{
        game_id: "g1", start_time: "2030-01-01T23:00:00Z", game_date: "2030-01-01", home: { abbr: "OKC", name: "Oklahoma City Thunder" }, away: { abbr: "CLE", name: "Cleveland Cavaliers" },
        players: [{
          player_id: "p1", name: "Donovan Mitchell", team: "CLE", opp: "OKC", position: "G", game_id: "g1", injury_status: null, inputs: {},
          markets: { rebounds: { label: "Rebounds", mean: 4, median: 4, sd: 2, support: "ok", support_note: "", range_80: [1, 7], thresholds: [], grid: { k0: 0, step: 1, p: [1, 0.95, 0.8, 0.6, 0.4, 0.2, 0.1] } } },
        }],
      }],
    } as unknown as EnginePropsBoard;
    const { board: b, info } = await withLivePolymarket("nba", board, new Set(["g1"]), new Date("2030-01-01T12:00:00Z"));
    expect(info.found).toBe(1);
    const th = b.games[0].players[0].markets.rebounds.thresholds;
    const two = th.find((t) => t.threshold === 2)!;
    expect(two.model_prob).toBe(0.8);
    expect(two.quotes[0]).toMatchObject({ provider: "polymarket_us", yes_bid: 0.57, yes_ask: 0.67, usable: false });
    expect(board.games[0].players[0].markets.rebounds.thresholds).toHaveLength(0); // the published board isn't changed
    expect(normName("Jaren Jackson Jr.")).toBe("jaren jackson");
  });
});
