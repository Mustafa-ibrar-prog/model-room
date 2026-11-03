import "server-only";
import { loadPropsBoard } from "@/server/engine/board";
import { getLeagueBoard } from "@/server/data";
import type { League } from "@/types/domain";

/** Days (YYYY-MM-DD, the league's game_date) that have upcoming games, from the game and props boards. */
export async function getUpcomingDates(league: League): Promise<string[]> {
  const [board, props] = await Promise.all([getLeagueBoard(league, "free"), loadPropsBoard(league)]);
  const out = new Set<string>();
  if (board.ok) for (const g of board.upcoming) out.add(g.gameDate);
  if (props.ok) for (const g of props.board.games) out.add(g.game_date);
  return [...out].sort();
}
