/** Sportsbook-line labels (TEST): Available / Pending / Unavailable from stored data only; never a number without a line. */
import { describe, expect, it } from "vitest";
import { lineStatus } from "@/lib/lineStatus";

const at = (pt: string) => new Date(`${pt}-08:00`);                 // Pacific standard time
const base = { league: "nba" as const, category: "points", hasLine: false, gameDate: "2026-11-27", gameStarted: false, fetch: null, now: at("2026-11-27T10:00:00") };

describe("line status", () => {
  it("available only when a stored line exists", () => {
    expect(lineStatus({ ...base, hasLine: true }).state).toBe("available");
  });
  it("today's and tomorrow's games are pending until the next of the three refreshes (7:00, 12:30, 4:00 PT)", () => {
    expect(lineStatus({ ...base, gameDate: "2026-11-28" }).reason).toBe("Checked at 12:30 PM PT.");
    expect(lineStatus({ ...base, now: at("2026-11-27T05:00:00") }).reason).toBe("Checked at 7:00 AM PT.");
    expect(lineStatus({ ...base, now: at("2026-11-27T13:00:00") }).reason).toBe("Checked at 4:00 PM PT.");
    expect(lineStatus({ ...base, gameDate: "2026-11-28", now: at("2026-11-27T17:00:00") }).reason).toBe("Checked at 7:00 AM PT.");
    expect(lineStatus({ ...base, now: at("2026-11-27T17:00:00") }).state).toBe("unavailable");      // today's last refresh passed
  });
  it("credit limit, failed fetch, player not listed: unavailable with the reason", () => {
    expect(lineStatus({ ...base, fetch: { status: "skipped_cap" } }).reason).toMatch(/credit limit/);
    expect(lineStatus({ ...base, fetch: { status: "error" } }).reason).toMatch(/failed/);
    const c = lineStatus({ ...base, fetch: { status: "captured" } });
    expect(c.state).toBe("unavailable");
    expect(c.reason).toMatch(/No sportsbook listed this player/);
  });
  it("an empty response is checked again at the next refresh, then unavailable after the last one", () => {
    expect(lineStatus({ ...base, fetch: { status: "empty" }, now: at("2026-11-27T09:00:00") }).reason).toMatch(/checked again at 12:30 PM PT/);
    expect(lineStatus({ ...base, fetch: { status: "empty" }, now: at("2026-11-27T16:31:00") }).state).toBe("unavailable");
    expect(lineStatus({ ...base, fetch: { status: "empty" }, gameStarted: true }).state).toBe("unavailable");
  });
  it("stats without sportsbook collection say so; a live Polymarket quote is labelled Polymarket, never 'sportsbook'", () => {
    expect(lineStatus({ ...base, category: "rebounds" }).reason).toMatch(/collected for points only/);
    expect(lineStatus({ ...base, league: "nfl", category: "receptions" }).reason).toMatch(/collected for receiving yards only/);
    const pm = lineStatus({ ...base, category: "assists", hasExchange: true });
    expect(pm).toMatchObject({ state: "available", label: "Polymarket" });
    expect(pm.reason).toMatch(/Polymarket US/);
    expect(lineStatus({ ...base, hasLine: true, hasExchange: true }).reason).toMatch(/sportsbooks/);
  });
  it("uses the Pacific date, including across daylight saving", () => {
    expect(lineStatus({ ...base, gameDate: "2027-06-02", now: new Date("2027-06-02T12:00:00Z") }).reason).toBe("Checked at 7:00 AM PT."); // 5:00 AM PDT
    expect(lineStatus({ ...base, gameDate: "2026-11-27", now: new Date("2026-11-28T07:00:00Z") }).state).toBe("unavailable"); // 11 PM PT same day
  });
});
