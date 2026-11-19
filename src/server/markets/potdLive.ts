import "server-only";
import type { League } from "@/types/domain";
import type { EnginePropsBoard } from "@/types/props";
import { loadPropsBoard } from "@/server/engine/board";
import { ownerLiveMarkets, withLivePolymarket } from "./polymarketLive";
import { strongestLiveProp, todaysGameIds, type LivePropPick } from "./potdPick";

/**
 * Pick of the Day, OWNER-ONLY live preview (TEST site): the strongest player prop on the published active board against
 * live Polymarket US prices, fetched at request time. Polymarket data is never stored, written to a file or shown to
 * anyone but the owner (polymarketLive.ts rules); this preview is NOT a recorded Pick of the Day and is never graded.
 */
export async function ownerLivePropPick(league: League, now = new Date()): Promise<{ pick: LivePropPick | null; checked: number; fetchedAt: string } | null> {
  if (!(await ownerLiveMarkets())) return null;
  const res = await loadPropsBoard(league);
  if (!res.ok) return null;
  const ids = todaysGameIds(res.board as EnginePropsBoard, now);
  if (!ids.size) return { pick: null, checked: 0, fetchedAt: now.toISOString() };
  const { board, info } = await withLivePolymarket(league, res.board, ids, now);
  return { ...strongestLiveProp(league, board, ids), fetchedAt: info.fetchedAt };
}
