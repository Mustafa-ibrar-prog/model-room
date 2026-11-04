import "server-only";
import { canAccess, gate } from "@/lib/entitlements";
import { loadHistoryFile, loadPerformanceFile } from "@/server/engine/board";
import type { Gate, League, TierId } from "@/types/domain";
import type { HistoryDay, HistoryGame, HistoryIndex, HistoryProp, Performance } from "@/types/history";

/**
 * Past dates. Final scores are on every plan. The projections recorded before each game (and the
 * player-prop record) are history, which is Pro. Nothing here is recomputed: it's the ledger as written.
 */
export interface HistoryView {
  date: string;
  dates: string[];
  firstRecorded: string | null;
  games: (Omit<HistoryGame, "pregame" | "result" | "market"> & {
    pregame: Gate<HistoryGame["pregame"]>;
    result: Gate<HistoryGame["result"]>;
    market: Gate<NonNullable<HistoryGame["market"]>> | null;
  })[];
  props: Gate<HistoryProp[]>;
  available: boolean;
}

export async function getHistoryIndex(league: League): Promise<HistoryIndex | null> {
  return loadHistoryFile<HistoryIndex>(league, "index");
}

export async function getHistoryDay(league: League, date: string, tier: TierId): Promise<HistoryView> {
  const [index, day] = await Promise.all([getHistoryIndex(league), loadHistoryFile<HistoryDay>(league, date)]);
  const dates = (index?.dates ?? []).filter((d) => d.games > 0).map((d) => d.date);
  return {
    date,
    dates,
    firstRecorded: index?.first_recorded ?? null,
    available: Boolean(day),
    games: (day?.games ?? []).map((g) => ({
      ...g,
      pregame: g.pregame ? gate(tier, "history", g.pregame) : null,
      result: g.result ? gate(tier, "history", g.result) : null,
      market: g.market ? gate(tier, "history", g.market) : null,
    })),
    props: canAccess(tier, "history") ? (day?.props ?? []) : gate(tier, "history", []),
  };
}

export async function getPerformance(league: League): Promise<Performance | null> {
  return loadPerformanceFile<Performance>(league);
}
