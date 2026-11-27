/**
 * Sportsbook-line label for a player card (TEST, Moose 2026-11-27). Pure: decides from what is stored, never fetches.
 *   available    a stored line exists for this player (the number is shown elsewhere)
 *   pending      not fetched yet, and a scheduled fetch will still try (tomorrow's games; today's before the runs)
 *   unavailable  the fetch happened or can no longer happen, and there is no line; the reason says why
 * A number is only ever shown for "available".
 */
export type LineState = "available" | "pending" | "unavailable";
export type LineStatus = { state: LineState; label: string; reason: string };
export type GameFetchStatus = { status: "captured" | "empty" | "skipped_cap" | "error"; mode?: string; at?: string | null };

const MAIN_END = { h: 8, m: 30 };        // 5:30 AM run window ends 8:30 AM PT
const RETRY_END = { h: 12, m: 30 };      // 9:30 AM retry window ends 12:30 PM PT

function ptParts(now: Date): { date: string; mins: number } {
  const f = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const p = Object.fromEntries(f.formatToParts(now).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, mins: Number(p.hour) * 60 + Number(p.minute) };
}

const A = (reason: string): LineStatus => ({ state: "available", label: "Available", reason });
const P = (reason: string): LineStatus => ({ state: "pending", label: "Pending", reason });
const U = (reason: string): LineStatus => ({ state: "unavailable", label: "Unavailable", reason });

export function lineStatus(o: {
  league: "nba" | "nfl";
  category: string;
  hasLine: boolean;
  gameDate: string;                       // the game's Pacific date
  gameStarted: boolean;
  fetch: GameFetchStatus | null;          // this game's outcome from the day's stored view, if any
  now: Date;
}): LineStatus {
  if (o.league === "nfl") return U("NFL player lines aren't collected yet.");
  if (o.category !== "points") return U("Only player-points lines are collected.");
  if (o.hasLine) return A("Captured from US sportsbooks.");
  const { date: today, mins } = ptParts(o.now);
  const f = o.fetch?.status;
  if (f === "captured") return U("No sportsbook listed this player.");
  if (f === "skipped_cap") return U("Daily credit limit reached; this game wasn't fetched.");
  if (f === "error") return U("The fetch for this game failed.");
  if (f === "empty") {
    return o.gameDate === today && mins < RETRY_END.h * 60 + RETRY_END.m && !o.gameStarted
      ? P("Books hadn't posted at 5:30 AM; retry at 9:30 AM PT.")
      : U("Books hadn't posted a line when we checked.");
  }
  if (o.gameDate > today) return P("Fetched at 5:30 AM PT on game day.");
  if (o.gameDate === today && mins < MAIN_END.h * 60 + MAIN_END.m && !o.gameStarted) return P("Fetched at 5:30 AM PT today.");
  return U("Not fetched for this game.");
}
