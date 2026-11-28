import { describe, expect, it } from "vitest";
import { buildEvidence, parseLeg, type EvidenceFile, type Sources } from "@/server/ai/evidence";
import { parlayPack } from "@/server/ai/factpack";
import { validateReviewAi } from "@/server/ai/validate";
import { evidenceBalance } from "@/lib/parlay/evidence";
import type { LegOption, ParlayPrice } from "@/lib/parlay/types";
import type { EngineBoard } from "@/types/engine";
import type { EnginePropsBoard } from "@/types/props";

/** Evidence packs (TEST, Moose 2026-11-28): built from stored data, stamped with source and time; gaps listed. */
const AT = "2026-11-28T02:26:23+00:00";
const board = {
  generated_at: AT, league: "nba", ratings: [
    { rank: 1, abbr: "NY", pace: 104.2, avg_margin: 8.1, last10_margin: 9.0 }, { rank: 20, abbr: "MIA", pace: 96.0, avg_margin: -2.0, last10_margin: -4.0 },
    ...Array.from({ length: 10 }, (_, i) => ({ rank: 2 + i, abbr: `T${i}`, pace: 99 + i * 0.3, avg_margin: 0, last10_margin: 0 })),
  ],
  upcoming: [{ game_id: "g1", start_time: "2026-11-29T00:30:00Z", home: { abbr: "NY" }, away: { abbr: "MIA" }, rest: { home_days: 1, away_days: 2, home_b2b: true, away_b2b: false },
    adjustments: { rest_points: -0.8, injury_points: 1.2 }, projection: { margin: 6.1, total: 224, margin_range_80: [-8, 20], total_range_80: [204, 244], pace: 101.2 },
    market: { spread: -12.5, total: 223.5, books: 8, captured_at: "2026-11-27T20:00:00Z", sources: ["the_odds_api"] },
    availability: { home: [], away: [{ player: "Bam Center", position: "C", status: "out", long_term: false, source: "nba_official", report_time: "2026-11-28T02:15:00Z" },
      { player: "Old Injury", position: "G", status: "out", long_term: true, source: "espn", report_time: "2026-10-01T00:00:00Z" }], updated_at: AT, sources: [] } }],
} as unknown as EngineBoard;
const props = {
  generated_at: AT, model: { version: "0.2.0" },
  games: [{ game_id: "g1", players: [{ player_id: "p1", name: "Jay Home", team: "NY", opp: "MIA", position: "C", injury_status: "Available",
    markets: { rebounds: { label: "Rebounds", mean: 10.4, range_80: [6, 15], support: "ok", thresholds: [], grid: { k0: 0, step: 1, p: [] } } },
    inputs: { projected_minutes: 33.0, teammates_out: "Kay Wing", usage_freed_by_absences: 0.06,
      contributions: { stats: { reb: { baseline: 9.8, minutes: 0.3, usage: 0.4, matchup: 0.2, simulation: -0.1, final: 10.4 } } } },
    recent: { games: [], values: { rebounds: [12, 11, 9, 13, 12, 8, 10, 9, 11, 7] } } }] }],
} as unknown as EnginePropsBoard;
const evf = {
  league: "nba", generated_at: AT, results_through: "2026-11-26", sources: { box_scores: "hoopR / sportsdataverse (ESPN)" },
  defense: { MIA: { C: { rebounds: { allowed: 16.1, rank: 2, of: 30, league_avg: 13.2, games: 18 } } } },
  players: { p1: { games: [], values: { rebounds: [12, 11, 9, 13, 12, 8, 10, 9, 11, 7, 14, 10, 12, 9, 11] }, season_games: 18,
    season: { rebounds: { avg: 10.6, sd: 2.1 } }, splits: { home_games: 9, away_games: 9, rebounds: { home: 11.5, away: 9.7 } },
    usage: { minutes: { last5: 34.6, season: 32.0 } } } },
} as unknown as EvidenceFile;
const src: Sources = { boards: { nba: board }, props: { nba: props }, evidence: { nba: evf } };
const leg = (id: string, p: number) => ({ id, p, label: "Jay Home 10+ rebounds", league: "nba", gameId: "g1", kind: "prop" } as unknown as LegOption);

describe("evidence packs", () => {
  it("parses leg ids into exact thresholds and sides", () => {
    expect(parseLeg("nba~g1~prop~p1~rebounds~b9.5~o")).toMatchObject({ K: 10, side: 1 });
    expect(parseLeg("nba~g1~prop~p1~rebounds~m10~u")).toMatchObject({ K: 10, side: -1 });
    expect(parseLeg("nba~g1~spread~away~-2.5")).toMatchObject({ kind: "spread", side: -1, line: -2.5 });
  });
  it("prop: model reasoning, form at 5/10/15, minutes, defense vs position, injuries, blowout risk, splits; every item sourced", () => {
    const e = buildEvidence([leg("nba~g1~prop~p1~rebounds~m10~o", 0.58)], src)["nba~g1~prop~p1~rebounds~m10~o"];
    const t = e.items.map((x) => x.text).join("\n");
    expect(t).toContain("Model projects 10.4 rebounds");
    expect(t).toContain("teammates out (usage) +0.4");
    expect(t).toContain("Last 5: 4 of 5 at 10+ (avg 11.4); 10: 6 of 10 at 10+ (avg 10.2); 15: 10 of 15 at 10+ (avg 10.5)");
    expect(t).toContain("MIA allow 16.1 rebounds a game to centers, 2nd most of 30");
    expect(t).toContain("Teammates out: Kay Wing. The model adds 6.0% usage");
    expect(t).toContain("MIA missing: Bam Center (C, out)");
    expect(t).not.toContain("Old Injury");                                            // long-term absences aren't news
    expect(t).toContain("Blowout risk");
    expect(t).toContain("At home he averages 11.5 rebounds (9 games) against 9.7 away");
    expect(t).toContain("Back-to-back: NY");
    for (const x of e.items) expect(x.source.length).toBeGreaterThan(0);
    const d = e.items.find((x) => x.kind === "matchup" && x.text.includes("allow"))!;
    expect(d.lean).toBe("supports");
    expect(e.items.find((x) => x.text.startsWith("Blowout"))!.lean).toBe("against");
    expect(e.missing.join(" ")).toContain("Starting lineups aren't confirmed");
    expect(e.missing.join(" ")).toContain("No defensive scheme");
  });
  it("the same facts flip their lean for the under", () => {
    const o = buildEvidence([leg("nba~g1~prop~p1~rebounds~m10~o", 0.58)], src)["nba~g1~prop~p1~rebounds~m10~o"];
    const u = buildEvidence([leg("nba~g1~prop~p1~rebounds~m10~u", 0.42)], src)["nba~g1~prop~p1~rebounds~m10~u"];
    expect(evidenceBalance(o).supports).toBe(evidenceBalance(u).against);
    expect(evidenceBalance(o).against).toBe(evidenceBalance(u).supports);
  });
  it("says what's missing instead of guessing", () => {
    const thin: Sources = { boards: { nba: board }, props: { nba: props }, evidence: {} };
    const e = buildEvidence([leg("nba~g1~prop~p1~rebounds~m10~o", 0.58)], thin)["nba~g1~prop~p1~rebounds~m10~o"];
    expect(e.missing.join(" ")).toContain("No defense-versus-position figure");
    expect(e.missing.join(" ")).toContain("Home/away split not shown");
    expect(e.items.some((x) => x.text.includes("allow"))).toBe(false);
  });
  it("the fact pack carries the evidence text and leans, never Polymarket numbers unless allowed", () => {
    const l = { ...leg("nba~g1~prop~p1~rebounds~m10~o", 0.58), gameLabel: "MIA @ NY", warnings: [], price: null, marketP: null, group: "Rebounds",
      polymarket: { implied: 0.52 } } as unknown as ParlayPrice["legs"][number];
    const ev = buildEvidence([l], src);
    const pack = parlayPack({ legs: [l], pairs: [], warnings: [], p: 0.58, range: [0.5, 0.6], independent: 0.58, correlationEffect: 1, fairAmerican: -138 } as unknown as ParlayPrice, ev);
    expect(pack.legs[0].evidence.length).toBe(ev[l.id].items.length);
    expect(JSON.stringify(pack)).not.toContain("52.0%");
  });
});

describe("board review validation", () => {
  it("keeps only listed candidates and claims backed by their own cited evidence", () => {
    const pack = { candidates: [{ id: "C1", label: "Jay Home 10+ rebounds", model_probability: "58.0%", evidence: [{ id: "E1", text: "MIA allow 16.1 rebounds a game to centers, 2nd most of 30." }] }] };
    const v = validateReviewAi({ overview: "Two clear patterns.", candidates: [
      { id: "C1", verdict: "worth investigating", why: { text: "MIA allow 16.1 rebounds a game to centers.", cites: ["E1"] }, risk: { text: "He shoots 45% from deep.", cites: ["E1"] } },
      { id: "C9", verdict: "worth investigating", why: { text: "x", cites: [] }, risk: { text: "y", cites: [] } },
    ] }, pack)!;
    expect(v.candidates).toHaveLength(1);
    expect(v.candidates[0].why.text).toContain("16.1");
    expect(v.candidates[0].risk.text).toBe("");
  });
});
