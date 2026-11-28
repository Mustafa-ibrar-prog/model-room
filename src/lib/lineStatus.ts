/**
 * Sportsbook-line label for a player card (TEST, Moose 2026-11-27). Pure: decides from what is stored, never fetches.
 *   available    a stored sportsbook line exists for this player (the number is shown elsewhere), or, labelled
 *                "Polymarket", a live Polymarket US quote (an exchange price, never called a sportsbook line)
 *   pending      not fetched yet, and a scheduled fetch will still try (tomorrow's games; today's before the runs)
 *   unavailable  the fetch happened or can no longer happen, and there is no line; the reason says why
 * A number is only ever shown for "available".
 */
export type LineState = "available" | "pending" | "unavailable";
export type LineStatus = { state: LineState; label: string; reason: string };
export type GameFetchStatus = { status: "captured" | "empty" | "skipped_cap" | "error"; mode?: string; at?: string | null };

/** The three full refreshes (Pacific; from 2026-11-28), each checking today's AND tomorrow's games. */
const REFRESHES = [{ at: 7 * 60, text: "7:00 AM" }, { at: 12 * 60 + 30, text: "12:30 PM" }, { at: 16 * 60, text: "4:00 PM" }];

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
  /** A live Polymarket US quote exists for this player and stat (TEST; an exchange, not a sportsbook). */
  hasExchange?: boolean;
  gameDate: string;                       // the game's Pacific date
  gameStarted: boolean;
  fetch: GameFetchStatus | null;          // this game's outcome from the day's stored view, if any
  now: Date;
}): LineStatus {
  if (o.hasLine) return A("Captured from US sportsbooks.");
  const bookStat = o.league === "nba" ? o.category === "points" : o.category === "receiving_yards";
  if (o.hasExchange) {
    return { state: "available", label: "Polymarket", reason: bookStat ? "Live Polymarket US price; no sportsbook line stored for this player yet." : "Live Polymarket US price. Sportsbook lines are collected for " + (o.league === "nba" ? "points" : "receiving yards") + " only (free plan)." };
  }
  if (!bookStat) return U(`No line: sportsbook lines are collected for ${o.league === "nba" ? "points" : "receiving yards"} only (free plan), and Polymarket hasn't listed this player.`);
  const { date: today, mins } = ptParts(o.now);
  const f = o.fetch?.status;
  if (f === "captured") return U("No sportsbook listed this player.");
  if (f === "skipped_cap") return U("Daily credit limit reached; this game wasn't fetched.");
  if (f === "error") return U("The fetch for this game failed.");
  const tomorrow = new Date(Date.parse(`${today}T12:00:00Z`) + 86400_000).toISOString().slice(0, 10);
  const next = REFRESHES.find((r) => r.at > mins);
  if (!o.gameStarted && (o.gameDate === today || o.gameDate === tomorrow)) {
    if (next) return P(f === "empty" ? `Books hadn't posted yet; checked again at ${next.text} PT.` : `Checked at ${next.text} PT.`);
    if (o.gameDate === tomorrow) return P(f === "empty" ? "Books hadn't posted yet; checked again at 7:00 AM PT." : "Checked at 7:00 AM PT.");
  }
  if (!o.gameStarted && o.gameDate > tomorrow) return P("Checked from the day before the game (7:00 AM, 12:30 PM, 4:00 PM PT).");
  if (f === "empty") return U("Books hadn't posted a line when we checked.");
  return U("Not fetched for this game.");
}
