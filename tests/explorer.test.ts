/** Props explorer: category → relevant players, filters, sorting, and plan gating. SYNTHETIC board. */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getExplorer, lineKey } from "@/server/data/explorer";
import { isLocked } from "@/types/domain";

const q = (ev: number | null) => ({
  provider: "polymarket_us", yes_bid: 0.4, yes_ask: 0.42, no_ask: 0.6, mid: 0.41, spread: 0.02, ask_size: null, fee_yes: 0.017, fee_no: 0.017,
  ev_yes: ev, ev_no: -0.2, captured_at: "2030-01-01T12:00:00+00:00", usable: true, flags: [],
});
const market = (mean: number, ev: number | null, grade: "strong" | "lean" | null = ev ? "lean" : null) => ({
  label: "x", mean, median: mean, sd: mean / 2, range_80: [0, mean * 2], support: "ok", support_note: "20 games",
  thresholds: [{ op: ">=", threshold: Math.round(mean), variant: null, model_prob: 0.5, model_prob_raw: 0.5, quotes: ev === null ? [] : [q(ev)],
    best: ev === null ? null : { yes: { provider: "polymarket_us", price: 0.42, fee: 0.017, ev, size: null }, no: null, edge: "yes" },
    edge_grade: { grade, reasons: [] } }],
});
const player = (id: string, name: string, pos: string, team: string, mk: Record<string, ReturnType<typeof market>>) => ({
  player_id: id, name, team, opp: team === "HOM" ? "AWY" : "HOM", position: pos, game_id: "g1", injury_status: null, inputs: { target_share: 0.2 }, markets: mk,
});
const board = {
  schema_version: 1, league: "nfl", kind: "player_props", generated_at: "2030-01-01T12:00:00+00:00", season: 2030, week: 1,
  model: { id: "nfl-props", version: "9.9.9", status: "provisional", fitted_at: null, sims: 10 },
  data: { last_ingest: null, results_through: null, markets: [], markets_not_published: [], comparison_rules: { max_age_min: 20, max_spread: 0.06, min_size: 50, min_ev: 0.02 } },
  performance: { backtest: null },
  games: [{ game_id: "g1", start_time: "2030-01-02T00:30:00+00:00", game_date: "2030-01-01", week: 1, home: { abbr: "HOM", name: "Home" }, away: { abbr: "AWY", name: "Away" },
    players: [
      player("qb", "Quarter Back", "QB", "HOM", { passing_yards: market(250, null), rushing_yards: market(12, null) }),
      player("wr1", "Wide One", "WR", "HOM", { receiving_yards: market(70, 0.03), rushing_yards: market(1, null) }),
      player("wr2", "Wide Two", "WR", "AWY", { receiving_yards: market(55, 0.08, "strong") }),
      player("rb", "Run Back", "RB", "AWY", { receiving_yards: market(20, null), rushing_yards: market(60, null) }),
    ] }],
};

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "mr-ex-"));
  process.env.MODELROOM_PUBLISHED_DIR = dir;
  writeFileSync(path.join(dir, "nfl_props.json"), JSON.stringify(board));
});
afterEach(() => {
  delete process.env.MODELROOM_PUBLISHED_DIR;
});
const now = new Date("2030-01-01T13:00:00Z");

describe("props explorer", () => {
  it("shows only the players a category is about", async () => {
    const x = await getExplorer("nfl", "plus", { cat: "passing_yards" }, now);
    if (!x.ok || isLocked(x.rows)) throw new Error("expected rows");
    expect(x.rows.map((r) => r.id)).toEqual(["qb"]);
    const ru = await getExplorer("nfl", "plus", { cat: "rushing_yards" }, now);
    if (!ru.ok || isLocked(ru.rows)) throw new Error("expected rows");
    expect(ru.rows.map((r) => r.id)).toEqual(["rb", "qb"]); // WR with ~1 yd projected is dropped
  });

  it("filters, searches and sorts by edge", async () => {
    const x = await getExplorer("nfl", "plus", { cat: "receiving_yards", sort: "edge" }, now);
    if (!x.ok || isLocked(x.rows)) throw new Error("expected rows");
    expect(x.rows.map((r) => r.id)).toEqual(["wr2", "wr1", "rb"]);
    const strong = await getExplorer("nfl", "plus", { cat: "receiving_yards", only: "strong" }, now);
    if (!strong.ok || isLocked(strong.rows)) throw new Error("expected rows");
    expect(strong.rows.map((r) => r.id)).toEqual(["wr2"]);
    const s = await getExplorer("nfl", "plus", { cat: "receiving_yards", q: "one" }, now);
    if (!s.ok || isLocked(s.rows)) throw new Error("expected rows");
    expect(s.rows.map((r) => r.id)).toEqual(["wr1"]);
    const team = await getExplorer("nfl", "plus", { cat: "receiving_yards", team: "AWY" }, now);
    if (!team.ok || isLocked(team.rows)) throw new Error("expected rows");
    expect(team.rows.every((r) => r.team === "AWY")).toBe(true);
  });

  it("sends Free the games and categories but no player data", async () => {
    const x = await getExplorer("nfl", "free", { cat: "receiving_yards" }, now);
    if (!x.ok) throw new Error("expected board");
    expect(isLocked(x.rows)).toBe(true);
    expect(x.games).toHaveLength(1);
    expect(JSON.stringify(x)).not.toContain("Wide One");
  });

  it("gates model inputs to Pro", async () => {
    const plus = await getExplorer("nfl", "plus", { cat: "receiving_yards" }, now);
    const pro = await getExplorer("nfl", "pro", { cat: "receiving_yards" }, now);
    if (!plus.ok || !pro.ok || isLocked(plus.rows) || isLocked(pro.rows)) throw new Error("expected rows");
    expect(isLocked(plus.rows[0].inputs)).toBe(true);
    expect(isLocked(pro.rows[0].inputs)).toBe(false);
  });

  it("opens one contract by its key, and never for Free", async () => {
    const x = await getExplorer("nfl", "plus", { cat: "receiving_yards" }, now);
    if (!x.ok || isLocked(x.rows)) throw new Error("expected rows");
    const r = x.rows[0];
    const key = lineKey(r.id, r.lines[0]);
    const d = await getExplorer("nfl", "plus", { cat: "receiving_yards", line: key }, now);
    if (!d.ok || isLocked(d.detail) || !d.detail) throw new Error("expected detail");
    expect(d.detail.row.id).toBe(r.id);
    expect(d.detail.line?.threshold).toBe(r.lines[0].threshold);
    const bad = await getExplorer("nfl", "plus", { cat: "receiving_yards", line: "nope~ge1" }, now);
    expect(bad.ok && bad.detail).toBe(null);
    const free = await getExplorer("nfl", "free", { cat: "receiving_yards", line: key }, now);
    expect(free.ok && isLocked(free.detail)).toBe(true);
  });

  it("searches every game when no game is picked, and keeps a day's games only", async () => {
    const s = await getExplorer("nfl", "plus", { cat: "receiving_yards", q: "wide" }, now);
    if (!s.ok || isLocked(s.rows)) throw new Error("expected rows");
    expect(s.searchAll).toBe(true);
    expect(s.rows.map((r) => r.name).sort()).toEqual(["Wide One", "Wide Two"]);
    const none = await getExplorer("nfl", "plus", { cat: "receiving_yards", date: "2030-02-01" }, now);
    expect(none.ok && none.games.length).toBe(0);
  });

  it("never presents the model's own threshold as a market line", async () => {
    const x = await getExplorer("nfl", "plus", { cat: "receiving_yards" }, now);
    if (!x.ok || isLocked(x.rows)) throw new Error("expected rows");
    const rb = x.rows.find((r) => r.id === "rb")!; // no quotes at all
    expect(rb.headline).toBeNull();
    expect(rb.atLine).toBeNull();
    expect(rb.preferred).toEqual({ kind: "none", reason: "no_market_line" });
    expect(rb.ladder.length).toBe(rb.lines.length);
    const wr = x.rows.find((r) => r.id === "wr1")!; // one quoted contract: 70+
    expect(wr.headline?.threshold).toBe(70);
    expect(wr.atLine).toMatchObject({ line: 69.5, push: 0 });
    expect(wr.ladder).toHaveLength(0);
    // The card with no market line opens by its own key.
    const card = await getExplorer("nfl", "plus", { cat: "receiving_yards", line: "rb~card" }, now);
    if (!card.ok || isLocked(card.detail) || !card.detail) throw new Error("expected detail");
    expect(card.detail.line).toBeNull();
  });

  it("gates the model's contribution record to Pro and reads it per market", async () => {
    const plus = await getExplorer("nfl", "plus", { cat: "receiving_yards" }, now);
    const pro = await getExplorer("nfl", "pro", { cat: "receiving_yards" }, now);
    if (!plus.ok || !pro.ok || isLocked(plus.rows) || isLocked(pro.rows)) throw new Error("expected rows");
    expect(isLocked(plus.rows[0].contributions)).toBe(true);
    const c = pro.rows[0].contributions;
    if (isLocked(c)) throw new Error("expected contributions");
    expect(c.steps).toBeNull(); // the synthetic board predates the recording
    expect(c.reason).toBe("not recorded for this projection");
  });

  it("carries past games and season averages as published, without padding or mixing in opportunity", async () => {
    const b = JSON.parse(JSON.stringify(board));
    const wr = b.games[0].players.find((p: { player_id: string }) => p.player_id === "wr1");
    wr.recent = {
      games: [
        { date: "2029-12-28", opp: "AAA", season: 2030, snap_pct: 80, targets: 9, carries: 0 },
        { date: "2029-12-21", opp: "BBB", season: 2030, snap_pct: 70, targets: 6, carries: 1 },
        { date: "2029-01-05", opp: "CCC", season: 2029, snap_pct: 60, targets: 4, carries: 0 },
      ],
      values: { receiving_yards: [88, 41, null], rushing_yards: [0, 3, 0] },
      season: { season: 2030, games: 2, avg: { receiving_yards: 64.5 }, opportunity: { snap_pct: 75, targets: 7.5 } },
      opportunity: [{ key: "snap_pct", label: "Snap share (%)" }, { key: "targets", label: "Targets" }, { key: "carries", label: "Carries" }],
    };
    writeFileSync(path.join(dir, "nfl_props.json"), JSON.stringify(b));
    const x = await getExplorer("nfl", "plus", { cat: "receiving_yards" }, now);
    if (!x.ok || isLocked(x.rows)) throw new Error("expected rows");
    const h = x.rows.find((r) => r.id === "wr1")!.history;
    expect(h.games.map((g) => g.value)).toEqual([88, 41, null]); // exactly the published games, newest first
    expect(h.games[2].season).toBe(2029); // an earlier season stays labelled
    expect(h.opportunity.map((o) => o.key)).toEqual(["snap_pct", "targets"]); // receiving: snaps and targets only
    expect(h.games[0].opp_).toEqual({ snap_pct: 80, targets: 9 });
    expect(h.season).toEqual({ season: 2030, games: 2, avg: 64.5, opportunity: { snap_pct: 75, targets: 7.5 } });
    expect(h.published).toBe(10);
    // A player on an older board (5 games, no season block) gets no season and no invented games.
    const rb = x.rows.find((r) => r.id === "rb")!.history;
    expect(rb.games).toEqual([]);
    expect(rb.season).toBeNull();
    expect(rb.published).toBe(5);
  });
});
