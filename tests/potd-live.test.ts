import { describe, expect, it } from "vitest";
import { formatProjection } from "@/lib/format";
import { adjustedProb, delta, ELIGIBLE, factorsFor, gameContext, hitHistory, lastForm, marginChance, matchupText, inGrid, liveReason, pmFee, priceCenter, rankOrder, RELIABILITY, RELIABILITY_0_2_3C, S1U, strongestLiveProp, TOP_N, todaysGameIds, towardShare, unaccountedOuts, type OfficialOut, type PlayerLogs } from "@/server/markets/potdPick";
import type { EnginePropsBoard } from "@/types/props";

const THETA = 0.0695;
const q = (yes: number | null, no: number | null, usable = true, fee: number | null = THETA) => ({
  provider: "polymarket_us", yes_bid: null, yes_ask: yes, no_ask: no, mid: null, spread: null, ask_size: null, fee_yes: 0, fee_no: 0,
  fee_coef: fee, ev_yes: null, ev_no: null, captured_at: "2026-11-22T18:00:00Z", usable, flags: [],
});
const th = (k: number, p: number, quotes: ReturnType<typeof q>[]) => ({ op: ">=" as const, threshold: k, variant: null, model_prob: p, model_prob_raw: p, quotes, best: null, edge_grade: { grade: null, reasons: [] } });
const grid = (n: number) => ({ k0: 0, step: 1, p: Array.from({ length: n }, (_, i) => Math.max(0, 1 - i / n)) });
type Th = ReturnType<typeof th>;

function player(id: string, name: string, points: Th[], opts: { gridLen?: number; mean?: number; pts?: Record<string, number>; reb?: Th[] } = {}) {
  const mk = (label: string, mean: number, thresholds: Th[], g = grid(opts.gridLen ?? 41)) => ({ label, mean, median: mean, sd: 5, support: "ok" as const, support_note: "200 games, 6000 minutes", range_80: [0, 0] as [number, number], thresholds, grid: g });
  return {
    player_id: id, name, team: "DEN", opp: "BOS", position: "C", game_id: "G1", injury_status: null,
    inputs: { teammates_out: "", opp_points_factor: 1.03, contributions: opts.pts ? { stats: { pts: opts.pts }, minutes: { usual: 30, projected: 31 } } : undefined },
    markets: {
      points: mk("Points", opts.mean ?? 27.4, points),
      rebounds: mk("Rebounds", 9, opts.reb ?? [th(10, 0.45, [q(0.4, 0.62, false)])]),
      blocks: mk("Blocks", 2, [th(1, 0.95, [q(0.5, 0.52)])]),
    },
  };
}

function board(start: string, players: ReturnType<typeof player>[], version = "0.2.0"): EnginePropsBoard {
  return {
    model: { version }, generated_at: "2026-11-22T17:00:00Z",
    games: [{ game_id: "G1", start_time: start, game_date: "2026-11-22", week: 1, home: { abbr: "DEN", name: "" }, away: { abbr: "BOS", name: "" }, players }],
  } as unknown as EnginePropsBoard;
}
const one = (start: string, points: Th[], gridLen = 41) => board(start, [player("1", "A", points, { gridLen })]);

const now = new Date("2026-11-22T20:00:00Z");
const TONIGHT = "2026-11-23T02:00:00Z";
const run = (b: EnginePropsBoard, logs?: PlayerLogs) => strongestLiveProp(b, todaysGameIds(b, now), logs);

describe("NBA Pick of the Day live preview", () => {
  it("is NBA only: points, rebounds, assists, threes", () => {
    expect([...ELIGIBLE]).toEqual(["points", "rebounds", "assists", "threes"]);
    expect(RELIABILITY.model).toBe("0.2.0");
  });

  it("qualifies on the reliability-adjusted probability and reports the after-fee edge against it", () => {
    const { pick, checked, diag } = run(one(TONIGHT, [th(25, 0.66, [q(0.55, 0.47)]), th(30, 0.30, [q(0.33, 0.69)])]));
    expect(checked).toBe(1);                                  // only the main line (25+, priced nearest 50¢) is judged
    expect(diag.offMain).toBe(1);                             // the 30+ rung is set aside, not compared
    expect(pick?.side).toBe("over");
    expect(pick?.line).toBe(24.5);
    expect(pick?.contract).toBe(25);
    expect(pick?.modelProb).toBeCloseTo(0.66, 3);
    expect(pick?.adjProb).toBeCloseTo(adjustedProb(0.66, 0), 3);   // no contributions: toward = 0
    expect(pick?.adjProb).toBeLessThan(0.66);                       // raw model sides ran overconfident in the backtest
    expect(pick?.fee).toBeCloseTo(pmFee(THETA, 0.55), 3);
    expect(pick?.edge).toBeCloseTo(adjustedProb(0.66, 0) - 0.55 - pmFee(THETA, 0.55), 3);
    expect(pick?.modelVersion).toBe("0.2.0");
  });

  it("marks down a projection that rests on adjustments (the Wembanyama case) and says why it was rejected", () => {
    // baseline 24.4, blowout -2.9, matchup -0.4: 13% of the projection comes from adjustments toward the Under
    const pts = { baseline: 24.4, minutes: 0, blowout: -2.9, usage: 0, pace: -0.3, matchup: -0.36, simulation: 0, final: 20.84 };
    const b = board(TONIGHT, [player("9", "W", [th(25, 0.35, [q(0.49, 0.52)])], { mean: 20.84, pts })]);
    expect(towardShare(pts, "under")).toBeCloseTo(3.26 / 24.4, 3);
    const out = run(b);
    expect(out.pick).toBeNull();                              // raw 65% Under, but about 55.6% after the adjustment
    expect(out.diag.belowProb).toBe(1);
    expect(out.rejected[0].why).toContain("after the reliability adjustment");
    expect(out.rejected[0].modelProb).toBeCloseTo(0.65, 3);
  });

  it("ranks by adjusted probability, not by the biggest gap", () => {
    const steady = player("1", "Steady", [th(20, 0.74, [q(0.6, 0.42)])], { mean: 24 });        // 74% raw, smaller edge
    const gap = player("2", "Gap", [th(25, 0.69, [q(0.45, 0.57)])], { mean: 29 });              // 69% raw, bigger edge
    const { pick } = run(board(TONIGHT, [steady, gap]));
    expect(pick?.player).toBe("Steady");
    expect(adjustedProb(0.69, 0) - 0.45 - pmFee(THETA, 0.45)).toBeGreaterThan(adjustedProb(0.74, 0) - 0.6 - pmFee(THETA, 0.6));
  });

  it("shows every qualifying main line, most reliable first, and none when nothing qualifies", () => {
    const steady = player("1", "Steady", [th(20, 0.74, [q(0.6, 0.42)])], { mean: 24 });
    const gap = player("2", "Gap", [th(25, 0.69, [q(0.45, 0.57)])], { mean: 29 });
    const weak = player("3", "Weak", [th(25, 0.58, [q(0.56, 0.46)])], { mean: 26 });
    const out = run(board(TONIGHT, [gap, weak, steady]));
    expect(out.picks.map((x) => x.player)).toEqual(["Steady", "Gap"]);    // Weak never forced in
    expect(out.pick?.player).toBe("Steady");
    expect(run(board(TONIGHT, [weak])).picks).toEqual([]);
  });

  describe("top 10 across the slate", () => {
    // n candidates over `games` games; probabilities step down so the expected order is known. All clear both bars.
    const slate = (n: number, games: number, prob = (i: number) => 0.80 - i * 0.005) => {
      const gs = Array.from({ length: games }, (_, gi) => ({
        game_id: `G${gi + 1}`, start_time: TONIGHT, game_date: "2026-11-22", week: 1, home: { abbr: `H${gi}`, name: "" }, away: { abbr: `A${gi}`, name: "" },
        players: [] as ReturnType<typeof player>[],
      }));
      for (let i = 0; i < n; i++) {
        const p = player(`p${i}`, `P${String(i).padStart(2, "0")}`, [th(20, prob(i), [q(0.5, 0.52)])], { mean: 24 });
        gs[i % games].players.push({ ...p, game_id: gs[i % games].game_id });   // round-robin: best props spread over games
      }
      return { model: { version: "0.2.0" }, generated_at: "2026-11-22T17:00:00Z", games: gs } as unknown as EnginePropsBoard;
    };

    it("more than 10 qualify: exactly 10 shown, ranked by adjusted probability, with the true total", () => {
      const out = run(slate(14, 3));
      expect(TOP_N).toBe(10);
      expect(out.qualified).toBe(14);
      expect(out.picks).toHaveLength(10);
      expect(out.picks.map((x) => x.player)).toEqual(Array.from({ length: 10 }, (_, i) => `P${String(i).padStart(2, "0")}`));
      for (let i = 1; i < 10; i++) expect(out.picks[i - 1].adjProb).toBeGreaterThanOrEqual(out.picks[i].adjProb);
      expect(out.pick?.player).toBe("P00");
    });

    it("fewer than 10 qualify: all are shown, none forced", () => {
      const weak = player("w", "Weak", [th(25, 0.58, [q(0.56, 0.46)])], { mean: 26 });
      const b = slate(6, 2);
      (b.games[0].players as unknown[]).push(weak);
      const out = run(b);
      expect(out.qualified).toBe(6);
      expect(out.picks).toHaveLength(6);
      expect(out.picks.some((x) => x.player === "Weak")).toBe(false);
    });

    it("zero qualify: empty list and the no-pick state", () => {
      const out = run(board(TONIGHT, [player("w", "Weak", [th(25, 0.58, [q(0.56, 0.46)])], { mean: 26 })]));
      expect(out.qualified).toBe(0);
      expect(out.picks).toEqual([]);
      expect(out.pick).toBeNull();
      expect(out.rejected.length).toBeGreaterThan(0);                       // closest misses still reported
    });

    it("ties in adjusted probability break deterministically (edge, then start, game, player)", () => {
      const tied = slate(12, 3, () => 0.72);                                   // identical probability and price for all
      const a = run(tied).picks.map((x) => `${x.gameId}:${x.player}`);
      const rev = { ...tied, games: [...tied.games].reverse().map((g) => ({ ...g, players: [...g.players].reverse() })) } as EnginePropsBoard;
      const b = run(rev).picks.map((x) => `${x.gameId}:${x.player}`);
      expect(a).toEqual(b);                                                    // input order never changes the result
      expect(a).toHaveLength(10);
      expect(a.slice(0, 4)).toEqual(["G1:P00", "G1:P03", "G1:P06", "G1:P09"]); // same start: game id, then player name
      expect(run(tied).qualified).toBe(12);
    });

    it("ranks globally across games, not a top 10 per game", () => {
      // game 1 holds the 12 strongest props; game 2 holds 3 weaker ones that would make a per-game top 10
      const b = slate(15, 1);
      const g2 = { ...b.games[0], game_id: "G2", players: b.games[0].players.splice(12).map((p) => ({ ...p, game_id: "G2" })) };
      (b.games as unknown[]).push(g2);
      const out = run(b);
      expect(out.qualified).toBe(15);
      expect(out.picks).toHaveLength(10);
      expect(out.picks.every((x) => x.gameId === "G1")).toBe(true);           // no per-game quota
      expect(new Set(out.picks.map((x) => x.player)).size).toBe(10);
    });

    it("rankOrder sorts the same way regardless of input order", () => {
      const out = run(slate(10, 2, () => 0.7)).picks;
      const shuffled = [...out].reverse().sort(rankOrder);
      expect(shuffled).toEqual(out);
    });
  });

  it("margin chances come from the game model's margin and error, both directions", () => {
    expect(marginChance(0, 13.3, 10)).toBeCloseTo(0.452, 2);              // pick'em: either team by 10+
    expect(marginChance(12, 13.3, 10)).toBeGreaterThan(marginChance(0, 13.3, 10));
    expect(marginChance(-12, 13.3, 15)).toBeCloseTo(marginChance(12, 13.3, 15), 9);
    const g = gameContext({ home: { abbr: "NY" }, away: { abbr: "IND" }, projection: { home_score: 118, away_score: 106, margin: 12, total: 224, pace: 100 } }, 13.3, "1.1.0");
    expect(g.favored).toBe("NY");
    expect(g.p10).toBeGreaterThan(g.p15);
    expect(g.p15).toBeGreaterThan(g.p20);
  });

  it("'what moved the projection' lists only adjustments that moved it, with signed one-decimal sizes", () => {
    const pts = { baseline: 24.4, minutes: -0.02, blowout: -2.9, usage: 0, pace: 0.3, matchup: -0.36, simulation: 0.1, final: 21.5 };
    const pl = player("9", "W", [th(25, 0.35, [q(0.49, 0.52)])], { mean: 21.5, pts });
    (pl.inputs as Record<string, unknown>).contributions = { stats: { pts }, minutes: { usual: 30, after_fill: 29.9, projected: 26.4 } };
    const f = factorsFor(pl as never, pl.markets.points as never, "points", "under");
    expect(f.map((x) => x.key)).toEqual(["blowout", "pace", "matchup"]);     // minutes -0.02 and usage 0 did not move it
    expect(f[0].text).toBe("Blowout risk: minutes cut to 26.4 from 29.9: −2.9 points.");
    expect(f[0].favors).toBe("pick");
    expect(f[1].favors).toBe("against");
    expect(f[2].text).toContain("BOS allows 3% more points to centers than average");
    expect(f.some((x) => /injury|listed|form|main line|reliab/i.test(x.text))).toBe(false);
    expect(delta(-0.36, "points")).toBe("−0.4 points");
  });

  it("keeps full precision internally; the projection displays as a whole number", () => {
    const { pick } = run(one(TONIGHT, [th(25, 0.66, [q(0.55, 0.47)])]));
    expect(pick?.projection).toBe(27.4);
    expect(pick?.difference).toBeCloseTo(2.9, 9);
    expect(formatProjection(pick!.projection)).toBe("27");
    expect(pick?.line).toBe(24.5);                            // market line never rounded
  });

  it("fee math: θ·p·(1−p), largest at 50¢", () => {
    expect(pmFee(THETA, 0.5)).toBeCloseTo(0.017375, 6);
    expect(pmFee(THETA, 0.9)).toBeCloseTo(0.006255, 6);
    expect(pmFee(THETA, 0)).toBe(0);
  });

  it("a pick that clears the probability bar but not the edge after fees is rejected", () => {
    const b = one(TONIGHT, [th(25, 0.6, [q(0.555, 0.47)])]);
    expect(run(b).pick).toBeNull();
    expect(run(b).checked).toBe(1);
    expect(run(b).rejected[0].why).toContain("edge after fees");
  });

  it("an unknown fee is never assumed to be zero", () => {
    expect(run(one(TONIGHT, [th(25, 0.8, [q(0.55, 0.47, true, null)])])).pick).toBeNull();
  });

  it("lines outside the model's grid are skipped, never clamped", () => {
    const out = run(one(TONIGHT, [th(25, 0.9, [q(0.3, 0.72)])], 21));
    expect(out.pick).toBeNull();
    expect(out.checked).toBe(0);
    expect(inGrid(grid(21), 20)).toBe(true);
    expect(inGrid(grid(21), 21)).toBe(false);
    expect(inGrid(grid(21), -1)).toBe(false);
    expect(inGrid(grid(21), 10.5)).toBe(false);
    expect(inGrid(undefined, 5)).toBe(false);
  });

  it("returns nothing when no quote clears the bar or the game isn't today", () => {
    expect(run(one(TONIGHT, [th(25, 0.58, [q(0.56, 0.46)])])).pick).toBeNull();
    expect(todaysGameIds(one("2026-11-24T02:00:00Z", []), now).size).toBe(0);
    expect(todaysGameIds(one("2026-11-22T19:00:00Z", []), now).size).toBe(0);  // already started
  });

  it("diagnostics count why each main line was dropped", () => {
    const b = board(TONIGHT, [
      player("1", "A", [th(25, 0.6, [q(0.555, 0.47)])]),               // passes the adjusted probability, fails the edge after fees
      player("2", "B", [th(20, 0.52, [q(0.5, 0.52)])]),                // neither side reaches 56.5%
      player("3", "C", [th(45, 0.9, [q(0.5, 0.52)])]),                 // outside a 41-point grid
      player("4", "D", [th(30, 0.7, [q(0.5, 0.52, true, null)])]),     // no fee
    ]);
    const { pick, diag } = run(b);
    expect(pick).toBeNull();
    expect(diag).toEqual({ quotes: 8, lines: 8, offMain: 0, unusable: 4, outsideGrid: 1, noFee: 1, belowProb: 1, belowEdge: 1, checked: 2, safeguard: 0 });
    const why = liveReason({ games: 1, found: 1, matched: 8 }, diag);
    expect(why).toContain("8 player-stat main lines checked");
    expect(why).toContain("1 under a 4-point edge after fees");
    expect(why).toContain("1 outside the model's range");
  });

  it("an extreme ladder contract never competes with the main line (the Josh Hart case)", () => {
    // main line 6+ priced near 50¢ (model 54%: no side reaches 56.5%); tail 12+ at 17¢/83¢ (model 5.7%: a 94% Under)
    const hart = player("5", "Josh Hart", [], { reb: [th(6, 0.54, [q(0.5, 0.52)]), th(12, 0.057, [q(0.17, 0.83)])] });
    const out = run(board(TONIGHT, [hart]));
    expect(out.pick).toBeNull();
    expect(out.diag.offMain).toBe(1);
    expect(out.diag.belowProb).toBe(1);
    expect(out.rejected).toEqual([]);
    expect(priceCenter({ yes_ask: 0.17, no_ask: 0.83 })).toBeCloseTo(0.17, 6);
    expect(priceCenter({ yes_ask: 0.5, no_ask: 0.52 })).toBeCloseTo(0.49, 6);
  });

  it("main-line history comes from box-score logs and is shown only with enough games", () => {
    const logs: PlayerLogs = { seasons: [2026, 2027], players: { "1": {
      "2027": { points: [30, 20, 25, 28, 31, 10], rebounds: [], assists: [], threes: [] },
      "2026": { points: Array.from({ length: 40 }, (_, i) => (i < 10 ? 30 : 20)), rebounds: [], assists: [], threes: [] } } } };
    expect(hitHistory(logs, "1", "points", 25)).toEqual({ thisSeason: { hits: 4, games: 6 }, lastSeason: { hits: 10, games: 40 } });
    expect(hitHistory(logs, "1", "rebounds", 5)).toEqual({ thisSeason: null, lastSeason: null });   // too few games: nothing shown
    expect(hitHistory(null, "1", "points", 25)).toEqual({ thisSeason: null, lastSeason: null });
    const { pick } = run(one(TONIGHT, [th(25, 0.66, [q(0.55, 0.47)])]), logs);
    expect(pick?.history.thisSeason).toEqual({ hits: 4, games: 6 });
  });

  it("reasons distinguish no listing, a failed fetch and no match", () => {
    const d0 = { quotes: 0, lines: 0, offMain: 0, unusable: 0, outsideGrid: 0, noFee: 0, belowProb: 0, belowEdge: 0, checked: 0, safeguard: 0 };
    expect(liveReason({ games: 4, found: 0, matched: 0 }, d0)).toBe("Polymarket has no market listed for any of today's 4 games yet.");
    expect(liveReason({ games: 4, found: 0, matched: 0, errors: 4, errorCodes: [0, 503] }, d0)).toContain("didn't answer for 4 of 4 games (timeout, HTTP 503)");
    expect(liveReason({ games: 4, found: 3, matched: 0 }, d0)).toContain("no player-prop line matched");
    expect(liveReason({ games: 0, found: 0, matched: 0 }, d0)).toBe("No NBA games left today.");
  });

  describe("S1u injury safeguard (approved 2026-11-23)", () => {
    // an Under on DEN that clears both bars: model 30% over at a 50c line -> 70% under
    const under = th(25, 0.3, [q(0.5, 0.5)]);
    const star = (minutes: number, starterRate: number, projected = 34, id = "S", team = "DEN") => ({
      ...player(id, "Star", [th(30, 0.5, [q(0.5, 0.52, false)])]), team,
      inputs: { projected_minutes: projected, starter_rate: starterRate, contributions: undefined },
      recent: { games: Array.from({ length: 10 }, () => ({ minutes })), values: {}, season: null },
    });
    const out = (id = "S"): OfficialOut => ({ playerId: id, name: "Star", team: "DEN", gameId: "G1", reportTime: "2026-11-22T23:30:00Z" });
    const slate = (extra: ReturnType<typeof star>[]) => board(TONIGHT, [player("1", "A", [under]), ...(extra as unknown as ReturnType<typeof player>[])]);
    const go = (b: EnginePropsBoard, outs: OfficialOut[] | null, safeguard = true) => strongestLiveProp(b, todaysGameIds(b, now), { outs, safeguard });

    it("skips the Under when an Out high-minute starter on his team is still projected, and explains why", () => {
      const r = go(slate([star(34, 0.95)]), [out()]);
      expect(r.picks).toHaveLength(0);
      expect(r.safeguarded).toHaveLength(1);
      expect(r.safeguarded[0].why).toContain("Star (34.0 minutes a game, still projected for 34.0)");
      expect(r.safeguarded[0].why).toContain("listed Out on the official injury report");
      expect(r.diag.safeguard).toBe(1);
      expect(liveReason({ games: 1, found: 1, matched: 1 }, r.diag)).toContain("left out by the injury safeguard");
    });
    it("never touches Overs", () => {
      const over = th(25, 0.7, [q(0.5, 0.5)]);
      const b = board(TONIGHT, [player("1", "A", [over]), star(34, 0.95) as unknown as ReturnType<typeof player>]);
      const r = go(b, [out()]);
      expect(r.picks.map((x) => x.side)).toEqual(["over"]);
      expect(r.safeguarded).toHaveLength(0);
    });
    it("keeps the Under when the Out player isn't a high-minute starter, isn't projected, or plays for the other team", () => {
      expect(go(slate([star(S1U.minMinutes - 1, 0.95)]), [out()]).picks).toHaveLength(1);          // under 28 minutes
      expect(go(slate([star(34, 0.4)]), [out()]).picks).toHaveLength(1);                            // mostly a bench player
      expect(go(slate([star(34, 0.95, 0)]), [out()]).picks).toHaveLength(1);                        // model already has him out
      expect(go(slate([star(34, 0.95, 34, "S", "BOS")]), [{ ...out(), team: "BOS" }]).picks).toHaveLength(1);  // opponent
      expect(go(slate([star(34, 0.95)]), [{ ...out(), gameId: "OTHER" }]).picks).toHaveLength(1);   // report for another game
    });
    it("only Out counts: a player not on the report (or Questionable / Doubtful, which never reach the list) changes nothing", () => {
      expect(go(slate([star(34, 0.95)]), []).picks).toHaveLength(1);
      expect(unaccountedOuts(slate([star(34, 0.95)]), new Set(["G1"]), []).size).toBe(0);
    });
    it("without a report the safeguard can't run and says so; it never assumes anyone is out", () => {
      const r = go(slate([star(34, 0.95)]), null);
      expect(r.safeguardActive).toBe(false);
      expect(r.picks).toHaveLength(1);
      const off = go(slate([star(34, 0.95)]), [out()], false);                    // the shadow reads the report itself
      expect(off.picks).toHaveLength(1) ;
    });
    it("needs at least 3 recent games to call him a high-minute starter", () => {
      const s = star(34, 0.95); s.recent.games = s.recent.games.slice(0, 2);
      expect(go(slate([s]), [out()]).picks).toHaveLength(1);
    });
  });

  it("each version uses its own reliability fit; 0.2.0's is unchanged", () => {
    expect(RELIABILITY).toMatchObject({ intercept: 0.0566, logitP: 0.7479, toward: -2.1913, model: "0.2.0" });
    expect(adjustedProb(0.65, 0)).toBeCloseTo(adjustedProb(0.65, 0, RELIABILITY), 12);
    expect(adjustedProb(0.65, 0.1, RELIABILITY_0_2_3C)).not.toBeCloseTo(adjustedProb(0.65, 0.1), 3);
    const b = one(TONIGHT, [th(25, 0.7, [q(0.5, 0.52)])]);
    const a = strongestLiveProp(b, todaysGameIds(b, now), { reliability: RELIABILITY_0_2_3C });
    expect(a.pick?.adjProb).toBeCloseTo(adjustedProb(0.7, 0, RELIABILITY_0_2_3C), 3);
  });

  it("recent form: last 5/10/15 and the middle 50% of the last 20, across seasons, oldest first", () => {
    const logs: PlayerLogs = { seasons: [2026, 2027], players: { "1": { "2026": { points: Array.from({ length: 12 }, (_, i) => i) }, "2027": { points: [20, 22, 24, 26, 28, 30] } } } };
    const f = lastForm(logs, "1", "points");
    expect(f.last5).toBeCloseTo((22 + 24 + 26 + 28 + 30) / 5);
    expect(f.last10).toBeCloseTo((8 + 9 + 10 + 11 + 20 + 22 + 24 + 26 + 28 + 30) / 10);
    expect(f.last15).toBeCloseTo((3 + 4 + 5 + 6 + 7 + 8 + 9 + 10 + 11 + 20 + 22 + 24 + 26 + 28 + 30) / 15);
    expect(f.range?.games).toBe(18);
    expect(f.range!.lo).toBeLessThan(f.range!.hi);
    expect(lastForm({ seasons: [2027], players: { "1": { "2027": { points: [1, 2, 3] } } } }, "1", "points")).toEqual({ last5: null, last10: null, last15: null, range: null });
  });

  it("matchup text says only what the model's matchup step did", () => {
    const pts = { baseline: 25, minutes: 0, blowout: 0, usage: 0, pace: 0, matchup: -0.43, simulation: 0, final: 24.6 };
    const p = { ...player("1", "A", [], { pts }), inputs: { opp_points_factor: 0.96, contributions: { stats: { pts } } } };
    expect(matchupText(p as never, p.markets.points as never, "points")).toBe("BOS allows 4% fewer points to centers than average, so the model lowered his projection by 0.4.");
    const flat = { ...p, inputs: { opp_points_factor: 1.01, contributions: { stats: { pts: { ...pts, matchup: 0.01 } } } } };
    expect(matchupText(flat as never, p.markets.points as never, "points")).toContain("didn't move his projection");
    expect(matchupText(player("1", "A", []) as never, p.markets.points as never, "points")).toBeNull();   // no breakdown: say nothing
  });
});
