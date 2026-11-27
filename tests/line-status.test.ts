/** Sportsbook-line labels (TEST): Available / Pending / Unavailable from stored data only; never a number without a line. */
import { describe, expect, it } from "vitest";
import { lineStatus } from "@/lib/lineStatus";

const at = (pt: string) => new Date(`${pt}-08:00`);                 // Pacific standard time
const base = { league: "nba" as const, category: "points", hasLine: false, gameDate: "2026-11-27", gameStarted: false, fetch: null, now: at("2026-11-27T10:00:00") };

describe("line status", () => {
  it("available only when a stored line exists", () => {
    expect(lineStatus({ ...base, hasLine: true }).state).toBe("available");
  });
  it("tomorrow's games are pending until their own 5:30 AM run", () => {
    const s = lineStatus({ ...base, gameDate: "2026-11-28" });
    expect(s.state).toBe("pending");
    expect(s.reason).toMatch(/5:30 AM PT on game day/);
  });
  it("today's games are pending before the morning run, unavailable once it should have run", () => {
    expect(lineStatus({ ...base, now: at("2026-11-27T05:00:00") }).state).toBe("pending");
    expect(lineStatus({ ...base, now: at("2026-11-27T09:00:00") }).state).toBe("unavailable");
  });
  it("credit limit, failed fetch, player not listed: unavailable with the reason", () => {
    expect(lineStatus({ ...base, fetch: { status: "skipped_cap" } }).reason).toMatch(/credit limit/);
    expect(lineStatus({ ...base, fetch: { status: "error" } }).reason).toMatch(/failed/);
    const c = lineStatus({ ...base, fetch: { status: "captured" } });
    expect(c.state).toBe("unavailable");
    expect(c.reason).toMatch(/No sportsbook listed this player/);
  });
  it("an empty 5:30 response is pending until the 9:30 retry window closes, then unavailable", () => {
    expect(lineStatus({ ...base, fetch: { status: "empty" }, now: at("2026-11-27T09:00:00") }).state).toBe("pending");
    expect(lineStatus({ ...base, fetch: { status: "empty" }, now: at("2026-11-27T12:31:00") }).state).toBe("unavailable");
    expect(lineStatus({ ...base, fetch: { status: "empty" }, gameStarted: true }).state).toBe("unavailable");
  });
  it("other stats and NFL are labelled unavailable (not collected)", () => {
    expect(lineStatus({ ...base, category: "rebounds" }).reason).toMatch(/Only player-points/);
    expect(lineStatus({ ...base, league: "nfl", category: "receiving_yards" }).reason).toMatch(/NFL player lines aren't collected/);
  });
  it("uses the Pacific date, including across daylight saving", () => {
    expect(lineStatus({ ...base, gameDate: "2027-06-02", now: new Date("2027-06-02T12:00:00Z") }).state).toBe("pending"); // 5:00 AM PDT
    expect(lineStatus({ ...base, gameDate: "2026-11-27", now: new Date("2026-11-28T07:00:00Z") }).state).toBe("unavailable"); // 11 PM PT same day
  });
});
