import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildCatalog, gridP } from "@/server/parlay/legs";
import { priceParlay } from "@/server/parlay/price";
import { gameSelection, propSelection } from "@/lib/parlay/cardMath";
import type { Table } from "@/server/parlay/correlations";
import type { EngineBoard } from "@/types/engine";
import type { EnginePropsBoard } from "@/types/props";
import type { DayView } from "@/server/markets/propLines";

/** Explorer cards (TEST, Moose 2026-11-27): one card per player per stat; every selection matches the server's leg. */
const TABLE = JSON.parse(readFileSync(path.join(__dirname, "..", "modeling", "data", "published", "parlay_correlations.json"), "utf8")) as Table;
const NOW = new Date("2026-11-27T20:00:00Z");
const grid = (k0: number, step: number, p: number[]) => ({ k0, step, p });
const G = grid(10, 1, [0.95, 0.92, 0.88, 0.84, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4, 0.35, 0.3, 0.26, 0.22, 0.18, 0.15, 0.12, 0.1]);
const MARKETS = ["points", "rebounds", "assists", "threes", "pra", "steals", "blocks"];
function market(label: string, g = G) {
  return { label, mean: 20.4, median: 20, sd: 6, support: "ok", support_note: "", range_80: [12, 28], grid: g,
    thresholds: [15, 20, 25].map((t) => ({ op: ">=", threshold: t, variant: null, model_prob: gridP({ grid: g } as never, t)!.p, quotes: [], best: null, edge_grade: { grade: null, reasons: [] } })) };
}
const player = (id: string, name: string, team: string, opp: string, injury = "Available") => ({
  player_id: id, name, team, opp, position: "G", game_id: "g1", injury_status: injury, inputs: {},
  recent: { games: [], values: Object.fromEntries(MARKETS.map((m) => [m, [22, 18, 25, 19, 30, 21, 17, 24, 20, 26, 40]])) },
  markets: Object.fromEntries(MARKETS.map((m) => [m, market(m[0].toUpperCase() + m.slice(1))])),
});
const props = () => ({ schema_version: 1, league: "nba", kind: "player_props", generated_at: "2026-11-27T18:00:00Z",
  games: [{ game_id: "g1", start_time: "2026-11-28T00:30:00Z", game_date: "2026-11-27", home: { abbr: "NY" }, away: { abbr: "MIA" }, injuries: {},
    players: [player("p1", "Jay Home", "NY", "MIA"), player("p2", "Kay Home", "NY", "MIA"), player("p3", "Lee Away", "MIA", "NY"), player("p4", "Out Guy", "NY", "MIA", "Out")] }] }) as unknown as EnginePropsBoard;
const sd = (m: number) => ({ model_prob: m, push_prob: 0, fair_odds: null, market_price: null, market_implied: null, ev_per_dollar: null });
const board = () => ({ generated_at: "2026-11-27T19:40:00Z", upcoming: [{
  game_id: "g1", start_time: "2026-11-28T00:30:00Z", game_date: "2026-11-27", status: "scheduled", neutral: false,
  home: { id: 1, abbr: "NY", name: "NY" }, away: { id: 2, abbr: "MIA", name: "MIA" }, rest: { home_days: 2, away_days: 2 }, adjustments: { rest_points: 0, injury_points: 0 },
  projection: { home_score: 114, away_score: 109, margin: 5, total: 223, spread: -5, home_win_prob: 0.65, away_win_prob: 0.35, margin_range_80: [-10, 20], total_range_80: [205, 241] },
  market: { spread: -2.5, total: 222, home_ml: -150, away_ml: 130, books: 9, captured_at: "2026-11-27T19:30:00Z", sources: ["the_odds_api"] },
  edges: { spread: 2.5, total: 1, home_prob_market: 0.58, away_prob_market: 0.42, home_prob_diff: 0.07, at_spread: { line: -2.5, home: sd(0.6), away: sd(0.4) },
    at_total: { line: 222, over: sd(0.52), under: sd(0.46) }, moneyline: { home: sd(0.65), away: sd(0.35) } },
  result: null, best: null, edge_grade: { grade: null, reasons: [] } }] }) as unknown as EngineBoard;
const view = (): DayView => ({ date: "2026-11-27", updated_at: "2026-11-27T13:45:00Z", games: { g1: { game_id: "g1", captured_at: "2026-11-27T13:45:00Z", unmatched_players: 0,
  players: { p1: { name: "Jay Home", alternates: 0, consensus_line: 19.5, consensus_over_novig: 0.49, last_update: "2026-11-27T13:45:00Z", books: [
    { book: "draftkings", title: "DraftKings", line: 19.5, over: -110, under: -110, over_novig: 0.5, last_update: "2026-11-27T13:40:00Z" },
    { book: "fanduel", title: "FanDuel", line: 19.5, over: 105, under: -125, over_novig: 0.47, last_update: "2026-11-27T13:41:00Z" },
    { book: "betmgm", title: "BetMGM", line: 21.5, over: 120, under: -150, over_novig: 0.43, last_update: "2026-11-27T13:42:00Z" } ] } } } } });
const gl = { league: "nba", generated_at: "2026-11-27T19:45:00Z", games: { g1: { commence_time: "2026-11-28T00:30:00Z", collected_at: "2026-11-27T19:45:00Z", books: {
  draftkings: { title: "DraftKings", spread: { line: -2.5, home: -110, away: -110, last_update: "2026-11-27T19:00:00Z" }, total: { line: 222, over: -105, under: -115, last_update: "2026-11-27T19:00:00Z" }, moneyline: { home: -145, away: 125, last_update: "2026-11-27T19:00:00Z" } },
  fanduel: { title: "FanDuel", spread: { line: -3, home: -102, away: -118, last_update: "2026-11-27T19:10:00Z" }, total: { line: 221.5, over: -110, under: -110, last_update: "2026-11-27T19:10:00Z" } } } } } };
const PM = { slug: "nba-mia-nyk-2026-11-27", teams: [{ id: 1, abbreviation: "NYK" }, { id: 2, abbreviation: "MIA" }], markets: [
  { sportsMarketType: "basketball_player_points", line: 20, metadata: { playerName: "Jay Home", teamId: 1 }, bestBidQuote: { value: "0.46" }, bestAskQuote: { value: "0.50" }, status: "MARKET_STATUS_OPEN" },
  { sportsMarketType: "basketball_player_rebounds", line: 23, metadata: { playerName: "Kay Home", teamId: 1 }, bestBidQuote: { value: "0.20" }, bestAskQuote: { value: "0.24" }, status: "MARKET_STATUS_OPEN" },
  { marketType: "spreads", sportsMarketType: "basketball_full_game_spread", line: 4.5, marketSides: [{ long: true, team: { abbreviation: "MIA" } }], bestBidQuote: { value: "0.53" }, bestAskQuote: { value: "0.55" }, status: "MARKET_STATUS_OPEN" },
  { marketType: "totals", sportsMarketType: "basketball_full_game_total", line: 224.5, marketSides: [{ long: true, description: "Over 224.5" }], bestBidQuote: { value: "0.41" }, bestAskQuote: { value: "0.45" }, status: "MARKET_STATUS_OPEN" },
  { marketType: "moneyline", sportsMarketType: "moneyline", marketSides: [{ long: true, team: { abbreviation: "MIA" } }], bestBidQuote: { value: "0.40" }, bestAskQuote: { value: "0.42" }, status: "MARKET_STATUS_OPEN" } ] };
const cat = () => buildCatalog("nba", board(), props(), { "2026-11-27": view() }, NOW, gl as never, { events: new Map([["g1", PM as never]]), fetchedAt: "2026-11-27T20:00:00Z" });

describe("explorer cards", () => {
  it("one card per player per stat; no duplicates; ruled-out players left out; all seven stats", () => {
    const c = cat().cards.get("g1")!;
    const keys = c.props.map((p) => p.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(c.props).toHaveLength(3 * 7);
    expect(c.props.some((p) => p.playerId === "p4")).toBe(false);
    expect(new Set(c.props.map((p) => p.market))).toEqual(new Set(MARKETS));
  });
  it("thresholds are model grid points (3-97%) plus exact market lines; book line L appears as K = L + 0.5", () => {
    const pts = cat().cards.get("g1")!.props.find((p) => p.key === "g1~p1~points")!;
    expect(pts.thresholds).toContain(20);                    // book 19.5 and Polymarket 20+
    expect(pts.thresholds).toContain(22);                    // BetMGM 21.5
    for (const k of pts.thresholds) expect(Number.isInteger(k)).toBe(true);
    expect(pts.bookLine).toBe(19.5);
    expect(pts.pm.map((x) => x.line)).toEqual([20]);
    const reb = cat().cards.get("g1")!.props.find((p) => p.key === "g1~p2~rebounds")!;
    expect(reb.pm.map((x) => x.line)).toEqual([23]);         // only Kay's own contract
    expect(cat().cards.get("g1")!.props.find((p) => p.key === "g1~p1~rebounds")!.pm).toEqual([]);
  });
  it("every threshold and side: the page's numbers equal the leg the server prices", () => {
    const c = cat();
    for (const card of c.cards.get("g1")!.props) {
      for (const K of card.thresholds) {
        for (const side of [1, -1] as const) {
          const s = propSelection(card, K, side);
          const id = s.ids.find((x) => card.legIds.includes(x)) ?? s.ids[s.ids.length - 1];
          for (const x of card.legIds) expect(c.legs.has(x)).toBe(true);
          const leg = c.resolve(id);
          if (s.p === null || s.p < 0.005 || s.p > 0.995) continue;
          expect(leg, id).not.toBeNull();
          const o = leg!.option;
          expect(o.p).toBeCloseTo(s.p, 4);
          expect(o.polymarket?.implied ?? null).toEqual(s.pm?.implied ?? null);
          expect(o.price?.american ?? null).toEqual(id.includes("~b") ? s.book?.american ?? null : null);
          expect(o.last10?.hits).toBe(s.last10?.hits);
        }
      }
    }
  });
  it("sportsbook price only at the exact line; Polymarket only for the exact contract; under takes the NO side", () => {
    const pts = cat().cards.get("g1")!.props.find((p) => p.key === "g1~p1~points")!;
    const o20 = propSelection(pts, 20, 1);
    expect(o20.book).toMatchObject({ american: 105, title: "FanDuel", books: 2, line: 19.5 });
    expect(o20.pm).toMatchObject({ bid: 0.46, ask: 0.5, implied: 0.48 });
    expect(o20.gap!.vs).toBe("Polymarket");
    const u20 = propSelection(pts, 20, -1);
    expect(u20.pm).toMatchObject({ bid: 0.5, ask: 0.54, implied: 0.52 });
    expect(u20.book!.american).toBe(-110);
    const o21 = propSelection(pts, 21, 1);
    expect(o21.book).toBeNull();
    expect(o21.pm).toBeNull();
    expect(o21.otherBookLines).toEqual([19.5, 21.5]);
    expect(o21.ids).toEqual(["nba~g1~prop~p1~points~m21~o"]);
    expect(propSelection(pts, 22, 1).book).toMatchObject({ american: 120, title: "BetMGM", line: 21.5 });
  });
  it("game cards: spread and total at any offered line use the engine formula; books and Polymarket only at exact lines", () => {
    const c = cat();
    const g = c.cards.get("g1")!.games;
    const spread = g.find((x) => x.kind === "spread")!;
    expect(spread.lines).toEqual(Array.from({ length: 17 }, (_, i) => -6.5 + i * 0.5));   // model lines -2.5 ± 4 (incl. FanDuel -3, PM home -4.5)
    const total = g.find((x) => x.kind === "total")!;
    expect(total.lines).toEqual(Array.from({ length: 25 }, (_, i) => 216 + i * 0.5));
    for (const card of [spread, total]) {
      for (const L of card.lines) {
        for (const side of [1, -1] as const) {
          const s = gameSelection(card, L, side);
          const leg = c.resolve(s.ids[0])!;
          expect(leg, s.ids[0]).not.toBeNull();
          expect(leg.option.p).toBeCloseTo(s.p!, 4);
          expect(leg.option.push ?? 0).toBeCloseTo(s.push, 4);
          expect(leg.option.price?.american ?? null).toEqual(s.book?.american ?? null);
          expect(leg.option.polymarket?.implied ?? null).toEqual(s.pm?.implied ?? null);
        }
      }
    }
    // listed consensus legs are identical to the resolver's
    expect(gameSelection(spread, -2.5, 1).p).toBeCloseTo(c.legs.get("nba~g1~spread~home~-2.5")!.option.p, 4);
    // away +4.5 is MIA's own YES contract; home -4.5 is its NO side (half line)
    expect(gameSelection(spread, -4.5, -1).pm).toMatchObject({ bid: 0.53, ask: 0.55 });
    expect(gameSelection(spread, -4.5, 1).pm).toMatchObject({ bid: 0.45, ask: 0.47 });
    expect(gameSelection(spread, -3, 1).book).toMatchObject({ american: -102, title: "FanDuel" });
    expect(gameSelection(spread, -3, 1).pm).toBeNull();
    expect(gameSelection(spread, -3, 1).push).toBeGreaterThan(0);              // whole line off consensus: formula push
    const ml = g.find((x) => x.kind === "moneyline")!;
    expect(gameSelection(ml, null, -1).pm).toMatchObject({ bid: 0.4, ask: 0.42 });
    expect(gameSelection(ml, null, 1).pm).toBeNull();           // no "NY wins" contract listed: the MIA NO side is not used
  });
  it("a resolved selection keeps its exact threshold and side in a parlay; made-up or off-grid ids are refused", () => {
    const c = cat();
    const p = priceParlay(["nba~g1~prop~p1~assists~m23~u", "nba~g1~spread~away~-4.5", "nba~g1~prop~p3~points~b19.5~o"], [c], TABLE, NOW);
    expect(p.rejected.map((r) => r.id)).toEqual(["nba~g1~prop~p3~points~b19.5~o"]);   // no book line for Lee: never invented
    expect(p.legs.map((l) => l.label)).toEqual(["Jay Home under 23 assists", "MIA +4.5"]);
    expect(c.resolve("nba~g1~prop~p1~points~m20.5~o")).toBeNull();
    expect(c.resolve("nba~g1~prop~p4~points~m20~o")).toBeNull();
    expect(c.resolve("nba~g1~prop~p1~points~m99~o")).toBeNull();
    expect(c.resolve("nfl~g1~prop~p1~points~m20~o")).toBeNull();
    expect(c.resolve("nba~g1~total~over~222.3")).toBeNull();
  });
});
