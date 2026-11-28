import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildCatalog, gridP, last10, linePs, mainLine, NO_PRICE, type Catalog } from "@/server/parlay/legs";
import { priceParlay } from "@/server/parlay/price";
import { relate, type Table, type Variable } from "@/server/parlay/correlations";
import { discoverPicks } from "@/server/parlay/discover";
import { allowedNumbers, cleanText, validateParlayAi } from "@/server/ai/validate";
import { parlayPack, sideOf } from "@/server/ai/factpack";
import { explainParlay } from "@/server/parlay/analyze";
import { pauseForTests } from "@/server/ai/gemini";
import { resetForTests } from "@/server/ai/limits";
import type { EngineBoard } from "@/types/engine";
import type { EnginePropsBoard } from "@/types/props";
import type { DayView } from "@/server/markets/propLines";

const TABLE = JSON.parse(readFileSync(path.join(__dirname, "..", "modeling", "data", "published", "parlay_correlations.json"), "utf8")) as Table;
const NOW = new Date("2026-11-27T20:00:00Z");

// ------------------------------------------------------------------------------------------------- fixtures
const grid = (k0: number, step: number, p: number[]) => ({ k0, step, p });
const pointsGrid = grid(10, 1, [0.95, 0.92, 0.88, 0.84, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4, 0.35, 0.3, 0.26, 0.22, 0.18, 0.15, 0.12, 0.1]);
function market(label: string, g = pointsGrid, ladder = [15, 20, 25, 40], support: "ok" | "limited" | "insufficient" = "ok") {
  return { label, mean: 20, median: 20, sd: 6, support, support_note: "", range_80: [12, 28] as [number, number], grid: g,
    thresholds: ladder.map((t) => ({ op: ">=", threshold: t, variant: null, model_prob: t === 40 ? 0.01 : gridP({ grid: g } as never, t)!.p, quotes: [], best: null, edge_grade: { grade: null, reasons: [] } })) };
}
function player(id: string, name: string, team: string, opp: string, injury: string | null = "Available") {
  return { player_id: id, name, team, opp, position: "G", game_id: "g1", injury_status: injury, inputs: {},
    markets: { points: market("Points"), rebounds: market("Rebounds", grid(2, 1, [0.9, 0.75, 0.6, 0.45, 0.32, 0.2, 0.12, 0.07]), [3, 5, 7]) } };
}
function propsBoard(): EnginePropsBoard {
  return {
    schema_version: 1, league: "nba", kind: "player_props", generated_at: "2026-11-27T18:00:00Z",
    games: [
      { game_id: "g1", start_time: "2026-11-28T00:30:00Z", game_date: "2026-11-27", home: { abbr: "NY" }, away: { abbr: "MIA" }, injuries: {},
        players: [player("p1", "Jay Home", "NY", "MIA"), player("p2", "Kay Home", "NY", "MIA"), player("p3", "Lee Away", "MIA", "NY"), player("p4", "Out Guy", "NY", "MIA", "Out"), player("p5", "Q Guy", "MIA", "NY", "Questionable")] },
      { game_id: "g2", start_time: "2026-11-28T03:00:00Z", game_date: "2026-11-27", home: { abbr: "LAL" }, away: { abbr: "BOS" }, injuries: {},
        players: [player("p6", "Mo West", "LAL", "BOS")] },
      { game_id: "g0", start_time: "2026-11-27T19:00:00Z", game_date: "2026-11-27", home: { abbr: "DAL" }, away: { abbr: "SAS" }, injuries: {},
        players: [player("p9", "Started Game", "DAL", "SAS")] },
    ],
  } as unknown as EnginePropsBoard;
}
function side(model_prob: number, push = 0, market_price: number | null = null) {
  return { model_prob, push_prob: push, fair_odds: null, market_price, market_implied: null, ev_per_dollar: null };
}
function board(): EngineBoard {
  const game = (id: string, start: string, home: string, away: string) => ({
    game_id: id, start_time: start, game_date: "2026-11-27", status: "scheduled", neutral: false,
    home: { id: 1, abbr: home, name: home }, away: { id: 2, abbr: away, name: away }, rest: { home_days: 2, away_days: 2 }, adjustments: { rest_points: 0, injury_points: 0 },
    projection: { home_score: 114, away_score: 109, margin: 5, total: 223, spread: -5, home_win_prob: 0.65, away_win_prob: 0.35, margin_range_80: null, total_range_80: null },
    market: { spread: -2.5, total: 222, home_ml: -150, away_ml: 130, books: 9, captured_at: "2026-11-27T19:30:00Z", sources: ["the_odds_api"] },
    edges: { spread: 2.5, total: 1, home_prob_market: 0.58, away_prob_market: 0.42, home_prob_diff: 0.07,
      at_spread: { line: -2.5, home: side(0.57), away: side(0.43) }, at_total: { line: 222, over: side(0.52, 0.02), under: side(0.46, 0.02) },
      moneyline: { home: side(0.65, 0, -150), away: side(0.35, 0, 130) } },
    result: null, best: null, edge_grade: { grade: null, reasons: [] },
  });
  return { generated_at: "2026-11-27T19:40:00Z", upcoming: [game("g1", "2026-11-28T00:30:00Z", "NY", "MIA"), game("g2", "2026-11-28T03:00:00Z", "LAL", "BOS"), game("g0", "2026-11-27T19:00:00Z", "DAL", "SAS")] } as unknown as EngineBoard;
}
function view(): DayView {
  const books = [
    { book: "draftkings", title: "DraftKings", line: 19.5, over: -110, under: -110, over_novig: 0.5, last_update: "2026-11-27T13:40:00Z" },
    { book: "fanduel", title: "FanDuel", line: 19.5, over: 105, under: -125, over_novig: 0.47, last_update: "2026-11-27T13:41:00Z" },
    { book: "betmgm", title: "BetMGM", line: 20.5, over: 120, under: -150, over_novig: 0.43, last_update: "2026-11-27T13:42:00Z" },
  ];
  return { date: "2026-11-27", updated_at: "2026-11-27T13:45:00Z", games: { g1: { game_id: "g1", captured_at: "2026-11-27T13:45:00Z", unmatched_players: 0,
    players: { p1: { name: "Jay Home", books, alternates: 0, consensus_line: 19.5, consensus_over_novig: 0.49, last_update: "2026-11-27T13:45:00Z" } } } } };
}
const catalog = (): Catalog => buildCatalog("nba", board(), propsBoard(), { "2026-11-27": view() }, NOW);

// ------------------------------------------------------------------------------------------------- legs
describe("parlay legs", () => {
  it("reads the calibrated grid, flags interpolation and refuses to go outside it", () => {
    const m = { grid: grid(60, 5, [0.9, 0.8, 0.7]) } as never;
    expect(gridP(m, 65)).toEqual({ p: 0.8, interpolated: false });
    expect(gridP(m, 67)!.interpolated).toBe(true);
    expect(gridP(m, 67)!.p).toBeCloseTo(0.76, 10);
    expect(gridP(m, 55)).toBeNull();
    expect(gridP(m, 75)).toBeNull();
  });
  it("half-point lines can't push; whole-number lines push at the line", () => {
    const m = { grid: pointsGrid } as never;
    const half = linePs(m, 19.5)!;
    expect(half.over).toBe(0.5);
    expect(half.under).toBe(0.5);
    expect(half.push).toBe(0);
    const whole = linePs(m, 20)!;
    expect(whole.over).toBe(0.45);
    expect(whole.under).toBeCloseTo(0.5, 10);
    expect(whole.push).toBeCloseTo(0.05, 10);
  });
  it("offers book lines with the best stored price at the consensus line, model lines without a price, and game lines", () => {
    const c = catalog();
    const over = c.legs.get("nba~g1~prop~p1~points~b19.5~o")!;
    expect(over.option.source).toBe("book_line");
    expect(over.option.price).toMatchObject({ american: 105, book: "fanduel", books: 2 });
    expect(over.option.marketP).toBeCloseTo((0.5 + (1 / 2.05) / (1 / 2.05 + 1.25 / 2.25)) / 2, 3); // no-vig median of books at 19.5
    const model = c.legs.get("nba~g1~prop~p2~points~m20~o")!;
    expect(model.option.source).toBe("model_line");
    expect(model.option.price).toBeNull();
    expect(c.legs.has("nba~g1~prop~p2~points~b19.5~o")).toBe(false); // no stored line for p2: never invented
    expect(c.legs.get("nba~g1~spread~home~-2.5")!.option).toMatchObject({ label: "NY -2.5", p: 0.57 });
    expect(c.legs.get("nba~g1~spread~away~-2.5")!.option.label).toBe("MIA +2.5");
    const ml = c.legs.get("nba~g1~ml~home")!.option;
    expect(ml.price?.american).toBe(-150);
    expect(ml.marketP! + c.legs.get("nba~g1~ml~away")!.option.marketP!).toBeCloseTo(1, 3);
  });
  it("drops started games, players ruled out, insufficient data and extreme thresholds", () => {
    const c = catalog();
    expect(c.games.map((g) => g.gameId)).toEqual(["g1", "g2"]);
    expect([...c.legs.keys()].some((k) => k.includes("~p4~"))).toBe(false);
    expect([...c.legs.keys()].some((k) => k.includes("~g0~"))).toBe(false);
    expect(c.legs.has("nba~g1~prop~p1~points~m40~o")).toBe(false); // 1%: outside 3%-97%
    expect(c.injuries.get("g1")?.some((x) => x.includes("Q Guy"))).toBe(true);
  });
});

describe("sportsbook odds on legs", () => {
  it("offers the line most books posted, never a median that no book offers", () => {
    expect(mainLine([{ line: 27.5 }, { line: 28.5 }, { line: 28.5 }])).toBe(28.5);
    expect(mainLine([{ line: 27.5 }, { line: 28.5 }])).toBe(27.5);                // tie: lower (both equally near the median 28)
    expect([27.5, 28.5]).toContain(mainLine([{ line: 27.5 }, { line: 28.5 }]));
  });
  it("keeps every book's quote and when it was updated; prices only count at the leg's exact line", () => {
    const o = catalog().legs.get("nba~g1~prop~p1~points~b19.5~o")!.option;
    expect(o.quotes!.map((q) => q.title).sort()).toEqual(["BetMGM", "DraftKings", "FanDuel"]);
    expect(o.quotes!.find((q) => q.book === "betmgm")).toMatchObject({ line: 20.5, price: 120 });
    expect(o.price!.books).toBe(2);                                               // BetMGM's 20.5 doesn't price the 19.5 leg
    expect(o.updatedAt).toBe("2026-11-27T13:42:00Z");
    expect(o.line).toBe(19.5);
  });
  it("model thresholds say there is no sportsbook price, in words", () => {
    const o = catalog().legs.get("nba~g1~prop~p2~points~m20~o")!.option;
    expect(o.source).toBe("model_line");
    expect(o.price).toBeNull();
    expect(o.noPrice).toContain(NO_PRICE);
    expect(o.noPrice).toContain("not a sportsbook line");
  });
  it("game lines: each book's spread, total and moneyline from R2; best price; no-vig; missing exact line explained", () => {
    const gl = { league: "nba", generated_at: "2026-11-27T19:45:00Z", games: { g1: { commence_time: "2026-11-28T00:30:00Z", collected_at: "2026-11-27T19:45:00Z", books: {
      draftkings: { title: "DraftKings", spread: { line: -2.5, home: -110, away: -110, last_update: "2026-11-27T19:00:00Z" }, total: { line: 222, over: -105, under: -115, last_update: "2026-11-27T19:00:00Z" }, moneyline: { home: -145, away: 125, last_update: "2026-11-27T19:00:00Z" } },
      fanduel: { title: "FanDuel", spread: { line: -3, home: -102, away: -118, last_update: "2026-11-27T19:10:00Z" }, moneyline: { home: -150, away: 130, last_update: "2026-11-27T19:10:00Z" } },
    } } } };
    const c = buildCatalog("nba", board(), propsBoard(), {}, NOW, gl);
    const home = c.legs.get("nba~g1~spread~home~-2.5")!.option;
    expect(home.price).toMatchObject({ american: -110, book: "draftkings", books: 1 });
    expect(home.quotes!.find((q) => q.book === "fanduel")!.line).toBe(-3);
    const away = c.legs.get("nba~g1~spread~away~-2.5")!.option;
    expect(away.quotes!.find((q) => q.book === "draftkings")).toMatchObject({ line: 2.5, price: -110 });
    expect(c.legs.get("nba~g1~ml~away")!.option.price).toMatchObject({ american: 130, book: "fanduel" });
    expect(c.legs.get("nba~g1~total~over~222")!.option.price!.american).toBe(-105);
    const g2 = c.legs.get("nba~g2~spread~home~-2.5")!.option;                     // no book data stored for g2
    expect(g2.price).toBeNull();
    expect(g2.noPrice).toBe(NO_PRICE);
  });
});

describe("last 10 games", () => {
  const pts = [30, 25, 24, 18, 27, 25, 31, 22, 26, 29, 40];
  it("uses the 10 most recent played games and the exact line; whole-number lines push", () => {
    const r = last10(pts, 24.5, 1, "line", "points", "Points Over 24.5")!;
    expect(r.games).toBe(10);
    expect(r.hits).toBe(7);
    expect(r.misses).toBe(3);
    expect(r.avg).toBeCloseTo(25.7, 1);
    expect(r.last5Hits).toBe(3);
    expect(r.text).toBe("Points Over 24.5: hit in 7 of last 10. Averaging 25.7 points. 3 of the last 5 hit.");
    const w = last10(pts, 25, 1, "line", "points", "Points Over 25")!;
    expect(w.pushes).toBe(2);
    expect(w.hits + w.misses + w.pushes).toBe(10);
    const u = last10(pts, 24.5, -1, "line", "points", "Points Under 24.5")!;
    expect(u.hits).toBe(3);
  });
  it("model thresholds count 'at least K' with no pushes; no game log means no record", () => {
    const r = last10(pts, 25, 1, "atleast", "points", "Points 25+")!;
    expect(r.hits).toBe(7);
    expect(r.pushes).toBe(0);
    expect(last10([], 25, 1, "atleast", "points", "x")).toBeNull();
    expect(last10(undefined, 25, 1, "atleast", "points", "x")).toBeNull();
    expect(last10([null, 12, null], 10, 1, "atleast", "points", "x")!.games).toBe(1);
  });
  it("every prop leg in the catalog carries its record when the board has a log", () => {
    const c = buildCatalog("nba", board(), { ...propsBoard(), games: propsBoard().games.map((g) => ({ ...g, players: g.players.map((p) => ({ ...p, recent: { games: [{ date: "2026-11-25", opp: "BOS", minutes: 34 }], values: { points: [22, 18, 30] } } })) })) } as never, { "2026-11-27": view() }, NOW);
    const o = c.legs.get("nba~g1~prop~p1~points~b19.5~o")!.option;
    expect(o.last10).toMatchObject({ games: 3, hits: 2 });
    expect(o.context?.usage).toBe("34.0 minutes a game over his last 1");
    expect(c.legs.get("nba~g1~prop~p1~rebounds~m5~o")!.option.last10).toBeNull();  // no rebounds log: none invented
  });
});

// ------------------------------------------------------------------------------------------------- correlations
describe("parlay correlations", () => {
  const prop = (o: Partial<Extract<Variable, { kind: "prop" }>>): Variable => ({ kind: "prop", league: "nba", gameId: "g1", playerId: "p1", market: "points", team: "NY", home: true, pos: null, ...o });
  it("same player uses the measured same-player coefficient; it is positive for points and rebounds", () => {
    const r = relate(TABLE, prop({}), prop({ market: "rebounds" }))!;
    expect(r.relation).toBe("same player");
    expect(r.r).toBeGreaterThan(0.2);
    expect(r.lo).toBeLessThanOrEqual(r.r);
    expect(r.hi).toBeGreaterThanOrEqual(r.r);
  });
  it("player vs game result flips sign for the away team", () => {
    const m: Variable = { kind: "margin", league: "nba", gameId: "g1" };
    const home = relate(TABLE, prop({}), m)!;
    const away = relate(TABLE, prop({ home: false, team: "MIA", playerId: "p3" }), m)!;
    expect(home.r).toBeCloseTo(-away.r, 10);
    expect(away.lo).toBeCloseTo(-home.hi, 10);
  });
  it("different games: independent (tested), with a small uncertainty band", () => {
    const r = relate(TABLE, prop({}), prop({ gameId: "g2", playerId: "p6", team: "LAL" }))!;
    expect(r).toMatchObject({ r: 0, relation: "different games" });
    expect(r.hi).toBeGreaterThan(0);
    expect(r.hi).toBeLessThan(0.06);
    expect(TABLE.leagues.nba.cross_game.independent).toBe(true);
    expect(TABLE.leagues.nfl.cross_game.independent).toBe(true);
  });
  it("NFL teammates are keyed by position: QB passing yards and WR receiving yards move together", () => {
    const qb = prop({ league: "nfl", market: "passing_yards", pos: "QB", playerId: "q" });
    const wr = prop({ league: "nfl", market: "receiving_yards", pos: "WR", playerId: "w" });
    expect(relate(TABLE, qb, wr)!.r).toBeGreaterThan(0.2);
  });
  it("returns null when a cell is missing or thin, so the caller falls back to bounds", () => {
    const t = structuredClone(TABLE);
    t.leagues.nba.cells["same|points|rebounds"].insufficient = true;
    expect(relate(t, prop({}), prop({ market: "rebounds" }))).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------- pricing
describe("parlay pricing", () => {
  const c = catalog();
  const P = (ids: string[], t: Table | null = TABLE, cats = [c]) => priceParlay(ids, cats, t, NOW);
  it("a single leg is its own probability", () => {
    const r = P(["nba~g1~spread~home~-2.5"]);
    expect(r.p).toBeCloseTo(0.57, 4);
    expect(r.independent).toBeCloseTo(0.57, 4);
    expect(r.fairAmerican).toBe(-133);
  });
  it("cross-game legs multiply; the range comes from the tested band", () => {
    const r = P(["nba~g1~spread~home~-2.5", "nba~g2~total~over~222"]);
    expect(r.p).toBeCloseTo(0.57 * 0.52, 4);
    expect(r.range![0]).toBeLessThanOrEqual(r.p!);
    expect(r.range![1]).toBeGreaterThanOrEqual(r.p!);
    expect(r.correlationEffect).toBeCloseTo(1, 3);
  });
  it("same-player overs win together more often than multiplying says; over and under work against each other", () => {
    const up = P(["nba~g1~prop~p1~points~m20~o", "nba~g1~prop~p1~rebounds~m5~o"]);
    expect(up.p!).toBeGreaterThan(up.independent!);
    expect(up.warnings.some((w) => w.text.includes("tend to win together"))).toBe(true);
    const down = P(["nba~g1~prop~p1~points~m20~o", "nba~g1~prop~p1~rebounds~m5~u"]);
    expect(down.p!).toBeLessThan(down.independent!);
  });
  it("nested lines on one stat: the stricter one decides; contradictory lines are impossible", () => {
    const nested = P(["nba~g1~prop~p1~points~m15~o", "nba~g1~prop~p1~points~m25~o"]);
    expect(nested.p).toBeCloseTo(c.legs.get("nba~g1~prop~p1~points~m25~o")!.option.p, 4);
    const impossible = P(["nba~g1~prop~p1~points~m25~o", "nba~g1~prop~p1~points~m15~u"]);
    expect(impossible.p).toBe(0);
    expect(impossible.warnings.some((w) => w.text.includes("can't both win"))).toBe(true);
  });
  it("spread and moneyline on the same team share the home margin (no double counting)", () => {
    const r = P(["nba~g1~spread~home~-2.5", "nba~g1~ml~home"]);
    expect(r.p).toBeCloseTo(0.57, 4); // covering -2.5 implies winning
  });
  it("missing correlations give bounds and no single number, never a guess", () => {
    const t = structuredClone(TABLE);
    t.leagues.nba.cells["team|points|points"].insufficient = true;
    const r = P(["nba~g1~prop~p1~points~m20~o", "nba~g1~prop~p2~points~m20~o", "nba~g2~total~over~222"], t);
    expect(r.p).toBeNull();
    expect(r.fairAmerican).toBeNull();
    const a = 0.5, b = 0.5;
    expect(r.range![0]).toBeCloseTo(Math.max(0, a + b - 1) * 0.52, 3);
    expect(r.range![1]).toBeCloseTo(Math.min(a, b) * 0.52, 3);
    expect(r.method).toMatch(/Bounds only/);
  });
  it("no table: refuses to price", () => {
    const r = P(["nba~g1~spread~home~-2.5"], null);
    expect(r.ok).toBe(false);
  });
  it("unknown or stale ids are rejected, not priced", () => {
    const r = P(["nba~g1~spread~home~-3.5", "nba~g1~spread~home~-2.5"]);
    expect(r.rejected.map((x) => x.id)).toEqual(["nba~g1~spread~home~-3.5"]);
    expect(r.legs).toHaveLength(1);
  });
  it("book price for the whole ticket only when every leg has a stored price", () => {
    expect(P(["nba~g1~ml~home", "nba~g2~ml~away"]).bookIfSeparate).not.toBeNull();
    expect(P(["nba~g1~ml~home", "nba~g1~prop~p2~points~m20~o"]).bookIfSeparate).toBeNull();
  });
  it("flags stale data", () => {
    const old = buildCatalog("nba", { ...board(), generated_at: "2026-11-25T00:00:00Z" } as EngineBoard, propsBoard(), {}, NOW);
    const r = priceParlay(["nba~g1~spread~home~-2.5"], [old], TABLE, NOW);
    expect(r.warnings.some((w) => w.text.includes("last updated"))).toBe(true);
  });
  it("caps the number of legs", () => {
    const ids = [...c.legs.keys()].slice(0, 11);
    expect(P(ids).ok).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------------- discovery
describe("picks to consider", () => {
  it("uses only legs with a stored price and market probability, one side per stat, ranked by score", () => {
    const picks = discoverPicks([catalog()], NOW);
    expect(picks.length).toBeGreaterThan(0);
    for (const p of picks) {
      expect(p.leg.price).not.toBeNull();
      expect(p.leg.marketP).not.toBeNull();
      expect(p.edge!).toBeGreaterThan(0);
    }
    const keys = picks.map((p) => `${p.leg.gameId}~${p.leg.kind}~${p.leg.playerId ?? ""}`);
    expect(new Set(keys).size).toBe(keys.length);
    for (let i = 1; i < picks.length; i++) expect(picks[i - 1].score).toBeGreaterThanOrEqual(picks[i].score);
    expect(picks.every((p) => p.invalidators.some((x) => x.includes("market knew more")))).toBe(true);
  });
});

// ------------------------------------------------------------------------------------------------- AI guardrails
describe("AI text validation", () => {
  const price = priceParlay(["nba~g1~spread~home~-2.5", "nba~g2~total~over~222"], [catalog()], TABLE, NOW);
  const pack = parlayPack(price, []);
  it("the fact pack carries labels and rounded engine numbers only", () => {
    const s = JSON.stringify(pack);
    expect(s).toContain("57.0%");
    for (const bad of ["grid", "params", "coef", '"sd"', '"mean"', "player_id", '"r":', "p1", "draftkings"]) expect(s).not.toContain(bad);
    expect(sideOf("nba~g1~spread~away~-2.5")).toBe(-1);
    expect(sideOf("nba~g1~prop~p1~points~m20~u")).toBe(-1);
  });
  it("removes sentences with numbers that aren't in the fact pack, and promises", () => {
    const allowed = allowedNumbers(pack);
    const c = cleanText("NY -2.5 is the anchor at 57.0%. This parlay is really 41% likely. It's a lock. Two legs, two games.", allowed);
    expect(c.text).toBe("NY -2.5 is the anchor at 57.0%. Two legs, two games.");
    expect(c.removed).toBe(2);
    expect(cleanText("Rounded to 57%.", allowed).removed).toBe(1);
    expect(cleanText("Fair odds would be +250.", allowed).removed).toBe(1);
  });
  it("keeps AI text short: one-sentence summary, at most two sentences per leg, two risks, two watch items", () => {
    const v = validateParlayAi({ summary: "One. Two. Three.", legs: [{ id: "L1", note: "A. B. C. D." }],
      riskiest: [{ id: "L1", reason: "x. y." }, { id: "L2", reason: "z." }, { id: "L1", reason: "w." }], watch: ["a.", "b.", "c."] }, pack)!;
    expect(v.summary).toBe("One.");
    expect(v.legs[0].note).toBe("A. B.");
    expect(v.riskiest).toHaveLength(2);
    expect(v.riskiest[0].reason).toBe("x.");
    expect(v.watch).toHaveLength(2);
  });
  it("drops ids Gemini invented", () => {
    const v = validateParlayAi({ summary: "Two separate games.", legs: [{ id: "L1", note: "Home side." }, { id: "L9", note: "Made up." }], riskiest: [{ id: "L7", reason: "x" }], watch: [] }, pack)!;
    expect(v.legs.map((l) => l.id)).toEqual(["L1"]);
    expect(v.riskiest).toEqual([]);
  });
});

describe("Analyze My Parlay", () => {
  const env = { ...process.env };
  beforeEach(() => {
    resetForTests();
    pauseForTests(0);
    process.env.VERCEL_ENV = "preview";
    process.env.GEMINI_API_KEY = "test-key-not-real";
    delete process.env.MODELROOM_GEMINI;
  });
  afterEach(() => {
    process.env = { ...env };
  });
  const c = catalog();
  const price = priceParlay(["nba~g1~spread~home~-2.5", "nba~g1~prop~p1~points~b19.5~o"], [c], TABLE, NOW);
  const who = { id: "11111111-1111-1111-1111-111111111111", net: "n1" };
  const answer = (obj: unknown) => vi.fn(async () => new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: JSON.stringify(obj) }] } }], usageMetadata: { promptTokenCount: 300, candidatesTokenCount: 120 } }), { status: 200 }));

  it("without a key: numbers still come back, AI says why it's missing", async () => {
    delete process.env.GEMINI_API_KEY;
    const r = await explainParlay(price, [c], who);
    expect(r).toMatchObject({ status: "unavailable", reason: "disabled" });
    expect(price.p).not.toBeNull();
  });
  it("off in production even with a key", async () => {
    process.env.VERCEL_ENV = "production";
    expect((await explainParlay(price, [c], who)).status).toBe("unavailable");
  });
  it("sends the key in a header (never the URL), no tools, a token cap; validates the answer; never changes numbers", async () => {
    const f = answer({ summary: "Both legs lean on New York. It is really 80% likely.", legs: [{ id: "L1", note: "Needs a win by 3 or more." }], riskiest: [{ id: "L2", reason: "Scoring swings." }], watch: ["Late scratches."] });
    const before = JSON.stringify(price);
    const r = await explainParlay(price, [c], who, f as unknown as typeof fetch);
    expect(r.status).toBe("ok");
    if (r.status === "ok") {
      expect(r.text.summary).toBe("Both legs lean on New York.");
      expect(r.text.removed).toBeGreaterThanOrEqual(1);
    }
    expect(JSON.stringify(price)).toBe(before);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).not.toContain("test-key-not-real");
    expect(url).toContain("gemini-3.5-flash-lite");
    expect((init.headers as Record<string, string>)["x-goog-api-key"]).toBe("test-key-not-real");
    const body = JSON.parse(init.body as string);
    expect(body.tools).toBeUndefined();
    expect(body.generationConfig.maxOutputTokens).toBeLessThanOrEqual(800);
    expect(init.body as string).not.toContain("test-key-not-real");
  });
  it("caches identical parlays: the second click makes no request", async () => {
    const f = answer({ summary: "Fine.", legs: [], riskiest: [], watch: [] });
    await explainParlay(price, [c], who, f as unknown as typeof fetch);
    const r2 = await explainParlay(price, [c], who, f as unknown as typeof fetch);
    expect(f).toHaveBeenCalledTimes(1);
    expect(r2).toMatchObject({ status: "ok", cached: true });
  });
  it("per-visitor daily cap", async () => {
    process.env.GEMINI_USER_DAILY = "2";
    for (const id of ["nba~g1~ml~home", "nba~g1~ml~away", "nba~g2~ml~home"]) {
      const p = priceParlay([id], [c], TABLE, NOW);
      const r = await explainParlay(p, [c], who, answer({ summary: "Ok.", legs: [], riskiest: [], watch: [] }) as unknown as typeof fetch);
      if (id === "nba~g2~ml~home") expect(r).toMatchObject({ status: "unavailable", reason: "user" });
      else expect(r.status).toBe("ok");
    }
  });
  it("site-wide daily cap", async () => {
    process.env.GEMINI_SITE_DAILY = "1";
    const a = priceParlay(["nba~g1~ml~home"], [c], TABLE, NOW);
    const b = priceParlay(["nba~g1~ml~away"], [c], TABLE, NOW);
    await explainParlay(a, [c], who, answer({ summary: "Ok.", legs: [], riskiest: [], watch: [] }) as unknown as typeof fetch);
    const r = await explainParlay(b, [c], { id: "22222222-2222-2222-2222-222222222222", net: "n2" }, answer({ summary: "Ok.", legs: [], riskiest: [], watch: [] }) as unknown as typeof fetch);
    expect(r).toMatchObject({ status: "unavailable", reason: "site" });
  });
  it("free quota exhausted (429): pauses AI until Pacific midnight and stops calling", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 429 }));
    const r = await explainParlay(price, [c], who, f as unknown as typeof fetch);
    expect(r).toMatchObject({ status: "unavailable", reason: "quota" });
    const other = priceParlay(["nba~g2~ml~home"], [c], TABLE, NOW);
    const r2 = await explainParlay(other, [c], who, f as unknown as typeof fetch);
    expect(r2).toMatchObject({ status: "unavailable", reason: "quota" });
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("service down or garbage answer: unavailable, numbers unaffected", async () => {
    const down = vi.fn(async () => { throw new Error("net"); });
    expect((await explainParlay(price, [c], who, down as unknown as typeof fetch)).status).toBe("unavailable");
    const junk = vi.fn(async () => new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: "not json" }] } }] }), { status: 200 }));
    expect((await explainParlay(priceParlay(["nba~g2~ml~away"], [c], TABLE, NOW), [c], who, junk as unknown as typeof fetch)).status).toBe("unavailable");
  });
});

describe("key security", () => {
  it("no client code or public env var can reach the Gemini key", () => {
    const builder = readFileSync(path.join(__dirname, "..", "src", "components", "parlay", "Builder.tsx"), "utf8");
    expect(builder).not.toMatch(/GEMINI_API_KEY|@\/server\/ai\/(gemini|limits|factpack|validate)"|generativelanguage/);
    const gem = readFileSync(path.join(__dirname, "..", "src", "server", "ai", "gemini.ts"), "utf8");
    expect(gem.startsWith('import "server-only"')).toBe(true);
    expect(gem).not.toMatch(/process\.env\.NEXT_PUBLIC|console\.(log|error|warn)/);
    expect(gem).not.toMatch(/\?key=/);
  });
});

// ------------------------------------------------------------------------------------------------- Polymarket US
import { contractsOf, gameContract, matchProps, sideQuote } from "@/server/parlay/polymarket";
import { picksPack } from "@/server/ai/factpack";

const PM_EVENT = {
  slug: "nba-mia-nyk-2026-11-27",
  teams: [{ id: 1, abbreviation: "NYK", name: "New York Knicks" }, { id: 2, abbreviation: "MIA", name: "Miami Heat" }],
  markets: [
    { sportsMarketType: "basketball_player_points", line: 20, metadata: { playerName: "Jay Home", teamId: 1 }, bestBidQuote: { value: "0.46" }, bestAskQuote: { value: "0.50" }, updatedAt: "2026-11-27T19:58:00Z", status: "MARKET_STATUS_OPEN" },
    { sportsMarketType: "basketball_player_points", line: 22, metadata: { playerName: "Jay Home", teamId: 1 }, bestBidQuote: { value: "0.36" }, bestAskQuote: { value: "0.40" }, status: "MARKET_STATUS_OPEN" },
    { sportsMarketType: "basketball_player_points", line: 18, metadata: { playerName: "Kay Home", teamId: 2 }, bestBidQuote: { value: "0.6" }, bestAskQuote: { value: "0.64" } },
    { sportsMarketType: "basketball_player_points", line: 10, metadata: { playerName: "Nobody Here", teamId: 1 }, bestBidQuote: { value: "0.6" }, bestAskQuote: { value: "0.64" } },
    { sportsMarketType: "basketball_player_rebounds", line: 5, metadata: { playerName: "Jay Home", teamId: 1 }, bestAskQuote: { value: "0.40" } },
    { marketType: "spreads", sportsMarketType: "basketball_full_game_spread", line: -2.5, marketSides: [{ long: true, team: { abbreviation: "NYK" } }], bestBidQuote: { value: "0.53" }, bestAskQuote: { value: "0.55" } },
    { marketType: "totals", sportsMarketType: "basketball_full_game_total", line: 222, marketSides: [{ long: true, description: "Over 222" }], bestBidQuote: { value: "0.49" }, bestAskQuote: { value: "0.51" } },
    { marketType: "moneyline", sportsMarketType: "moneyline", marketSides: [{ long: true, team: { abbreviation: "MIA" } }], bestBidQuote: { value: "0.40" }, bestAskQuote: { value: "0.42" } },
    { marketType: "totals", sportsMarketType: "basketball_first_half_total", line: 110, marketSides: [{ long: true, description: "Over 110" }], bestBidQuote: { value: "0.5" }, bestAskQuote: { value: "0.52" } },
  ],
};
const pmCatalog = () => buildCatalog("nba", board(), propsBoard(), { "2026-11-27": view() }, NOW, null,
  { events: new Map([["g1", PM_EVENT as never]]), fetchedAt: "2026-11-27T20:00:00Z" });

describe("Polymarket US: exact matching only", () => {
  it("parses props and full-game lines; ignores partial-game markets", () => {
    const cs = contractsOf(PM_EVENT as never);
    expect(cs.filter((c) => c.kind === "prop")).toHaveLength(5);
    expect(cs.filter((c) => c.kind === "total")).toHaveLength(1);
  });
  it("matches a player only by unique full name AND team; skips and counts everything else", () => {
    const m = matchProps("nba", contractsOf(PM_EVENT as never), [
      { playerId: "p1", name: "Jay Home", team: "NY" }, { playerId: "p2", name: "Kay Home", team: "NY" }]);
    expect(m.matched).toBe(3);
    expect(m.skipped).toEqual({ ambiguous: 0, teamMismatch: 1, notOnBoard: 1 });
    const twins = matchProps("nba", contractsOf(PM_EVENT as never), [{ playerId: "a", name: "Jay Home", team: "NY" }, { playerId: "b", name: "Jay Home", team: "NY" }]);
    expect(twins.matched).toBe(0);
    expect(twins.skipped.ambiguous).toBe(3);
  });
  it("'20+' equals over 19.5 and the model's 20+; the NO side prices the unders", () => {
    const c = pmCatalog();
    const over = c.legs.get("nba~g1~prop~p1~points~b19.5~o")!.option.polymarket!;
    expect(over).toMatchObject({ bid: 0.46, ask: 0.5, implied: 0.48, spread: 0.04, updatedAt: "2026-11-27T19:58:00Z", liquidity: null });
    expect(c.legs.get("nba~g1~prop~p1~points~b19.5~u")!.option.polymarket).toMatchObject({ bid: 0.5, ask: 0.54, implied: 0.52 });
    expect(c.legs.get("nba~g1~prop~p1~points~m20~o")!.option.polymarket!.implied).toBe(0.48);
  });
  it("a Polymarket line the model ladder lacks becomes its own leg, priced by the model's grid", () => {
    const c = pmCatalog();
    const o = c.legs.get("nba~g1~prop~p1~points~p22~o")!.option;
    expect(o.source).toBe("exchange_line");
    expect(o.p).toBe(0.4);                                                    // grid at 22
    expect(o.price).toBeNull();
    expect(o.polymarket!.implied).toBe(0.38);
  });
  it("one-sided books give no implied probability", () => {
    const o = pmCatalog().legs.get("nba~g1~prop~p1~rebounds~m5~o")!.option.polymarket!;
    expect(o.implied).toBeNull();
    expect(o.ask).toBe(0.4);
  });
  it("game lines: same team and line only; NO side only on half-point lines; moneyline never from the opponent's NO", () => {
    const c = pmCatalog();
    expect(c.legs.get("nba~g1~spread~home~-2.5")!.option.polymarket!.implied).toBe(0.54);
    expect(c.legs.get("nba~g1~spread~away~-2.5")!.option.polymarket!.implied).toBe(0.46);
    expect(c.legs.get("nba~g1~total~over~222")!.option.polymarket!.implied).toBe(0.5);
    expect(c.legs.get("nba~g1~total~under~222")!.option.polymarket).toBeUndefined();   // whole line can push
    expect(c.legs.get("nba~g1~ml~away")!.option.polymarket!.implied).toBe(0.41);
    expect(c.legs.get("nba~g1~ml~home")!.option.polymarket).toBeUndefined();
    expect(gameContract("nba", contractsOf(PM_EVENT as never), "spread", "NY", "MIA", -3.5, true)).toBeNull();
    expect(c.pm).toMatchObject({ eventsFound: 1, games: 2 });
  });
  it("no Polymarket data without the private view: the public catalog is unchanged", () => {
    const c = catalog();
    expect([...c.legs.values()].some((l) => l.option.polymarket)).toBe(false);
    expect(c.pm).toBeUndefined();
  });
  it("sideQuote: closed or crossed books are not priced", () => {
    const base = { kind: "prop" as const, line: 20, bid: 0.6, ask: 0.5, fee: null, status: "open", updatedAt: null, title: "x" };
    expect(sideQuote(base, true, "t", "x").implied).toBeNull();
    expect(sideQuote({ ...base, bid: 0.4, status: "closed" }, true, "t", "x").implied).toBeNull();
  });
});

describe("Polymarket picks and Gemini", () => {
  const env = { ...process.env };
  afterEach(() => { process.env = { ...env }; });
  it("picks compare the model with Polymarket separately from sportsbooks", () => {
    const picks = discoverPicks([pmCatalog()], NOW, 50);
    const pm = picks.filter((p) => p.benchmark === "polymarket");
    expect(pm.length).toBeGreaterThan(0);
    for (const p of pm) expect(p.edge).toBeCloseTo(p.leg.p - p.leg.polymarket!.implied!, 4);
  });
  it("Polymarket numbers are withheld from Gemini unless MODELROOM_PM_TO_GEMINI=on", () => {
    const picks = discoverPicks([pmCatalog()], NOW, 50).filter((p) => p.benchmark === "polymarket");
    delete process.env.MODELROOM_PM_TO_GEMINI;
    const off = picksPack(picks, []);
    for (const p of off.picks) {
      expect(p.market_probability).toBe("withheld");
      expect(p.gap).toBe("withheld");
      expect(p.market).not.toContain("Polymarket");
    }
    process.env.MODELROOM_PM_TO_GEMINI = "on";
    expect(JSON.stringify(picksPack(picks, []))).toContain("Polymarket US");
  });
});

