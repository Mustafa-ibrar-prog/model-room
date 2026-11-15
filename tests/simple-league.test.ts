/** The simplified league surface: what a card leads with, and that it never invents a market. */
import { describe, expect, it } from "vitest";
import { headlineFor, historyCaveat, listedStatus, listedText, marketLine, playerSub } from "@/components/league/simple";
import { browseHref } from "@/components/league/href";
import { NAV } from "@/components/layout/nav";
import type { ExplorerRow } from "@/server/data/explorer";
import type { PropLineView } from "@/types/props";

const line = (threshold: number, modelProb: number, quoted = false, op: ">=" | ">" = ">="): PropLineView =>
  ({
    op, threshold, variant: null, modelProb, modelProbRaw: modelProb, edgeGrade: null, edgeReasons: [], best: null,
    quotes: quoted ? [{ provider: "manual", yesBid: 0.5, yesAsk: 0.54, noAsk: 0.5, mid: 0.52, spread: 0.04, askSize: null, feeYes: 0, feeNo: 0, evYes: 0.01, evNo: -0.05, capturedAt: "2030-01-01T00:00:00Z", usable: true, flags: [] }] : [],
  }) as unknown as PropLineView;

const row = (over: Partial<ExplorerRow>): ExplorerRow =>
  ({
    id: "p1", name: "Test Player", team: "NY", opp: "IND", position: "G", gameId: "g1", mean: 22.8, median: 21, range80: [9, 39],
    support: "ok", supportNote: "192 games, 6724 minutes", headline: null, ladder: [line(15, 0.797), line(20, 0.6), line(30, 0.231)], lines: [],
    ...over,
  }) as unknown as ExplorerRow;

describe("what a player card leads with", () => {
  it("with no market line, quotes the model threshold nearest the projection, in plain words", () => {
    const h = headlineFor(row({}))!;
    expect(h.fromMarket).toBe(false);
    expect(h.marketProb).toBeNull();
    expect(h.threshold).toBe(20);
    expect(h.thresholdText).toBe("20 or more");
    expect(h.prob).toBeCloseTo(0.6);
    expect(h.belowProb).toBeCloseTo(0.4);
    expect(h.belowText).toBe("below 20");
  });

  it("never treats the model's own ladder as a market line", () => {
    expect(marketLine(row({}))).toBeNull();
    // a headline contract with no quotes is still not a market line
    expect(marketLine(row({ headline: line(20.5, 0.55, false, ">") }))).toBeNull();
    expect(headlineFor(row({ headline: line(20.5, 0.55, false, ">") }))!.fromMarket).toBe(false);
  });

  it("uses the quoted contract when a market really has one", () => {
    const h = headlineFor(row({ headline: line(20.5, 0.57, true, ">") }))!;
    expect(h.fromMarket).toBe(true);
    expect(h.threshold).toBe(20.5);
    expect(h.thresholdText).toBe("more than 20.5");
    expect(h.belowText).toBe("20.5 or less");
    expect(h.marketProb).not.toBeNull();
  });

  it("has nothing to say when no threshold is published, rather than making one up", () => {
    expect(headlineFor(row({ ladder: [] }))).toBeNull();
  });

  it("flags thin history and stays quiet when history is fine", () => {
    expect(historyCaveat(row({}))).toBeNull();
    expect(historyCaveat(row({ support: "limited", supportNote: "only 12 games, 259 minutes" }))).toBe("Limited history — 12 games on record");
    expect(historyCaveat(row({ support: "insufficient", supportNote: "only 3 games" }))).toBe("Very little history — 3 games on record");
    expect(historyCaveat(row({ support: "limited", supportNote: "new role" }))).toBe("Limited history behind this number");
  });

  it("describes the player without jargon, with or without a position", () => {
    expect(playerSub(row({}))).toBe("NY G · vs IND");
    expect(playerSub(row({ position: "" }))).toBe("NY · vs IND");
  });
});

describe("a player the injury report lists as out", () => {
  const feed = [{ team: "NY", rows: [{ player: "Test Player", status: "out" }, { player: "Other", status: "questionable" }] }];
  it("is flagged from the live feed, by team and name", () => {
    expect(listedStatus(feed, { name: "Test Player", team: "NY" })).toBe("out");
    expect(listedStatus(feed, { name: "Other", team: "NY" })).toBe("questionable");
    expect(listedText("out")).toMatch(/assumes he plays/);
  });
  it("says nothing when the feed is missing or does not list him", () => {
    expect(listedStatus(null, { name: "Test Player", team: "NY" })).toBeNull();
    expect(listedStatus(feed, { name: "Test Player", team: "IND" })).toBeNull();
    expect(listedStatus([{ team: "NY", rows: [{ player: "Test Player", status: "available" }] }], { name: "Test Player", team: "NY" })).toBeNull();
  });
});

describe("navigation", () => {
  it("is home, the four sports sections and performance", () => {
    expect(NAV.map((n) => n.label)).toEqual(["Home", "NBA Props", "NFL Props", "NBA", "NFL", "Performance"]);
    expect(NAV.map((n) => n.href)).toEqual(["/", "/nba-props", "/nfl-props", "/nba", "/nfl", "/performance"]);
  });

  it("builds league links from only the parts that are set", () => {
    expect(browseHref("nba", {})).toBe("/nba-props");
    expect(browseHref("nfl", { game: "g1", cat: "passing_yards" })).toBe("/nfl-props?game=g1&cat=passing_yards");
    expect(browseHref("nba", { game: "g1", player: "p9", q: undefined })).toBe("/nba-props?game=g1&player=p9");
  });
});
