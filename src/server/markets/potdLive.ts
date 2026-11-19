import "server-only";
import type { League } from "@/types/domain";
import type { EnginePropsBoard } from "@/types/props";
import { loadPropsBoard } from "@/server/engine/board";
import { isProduction } from "@/lib/auth-config";
import { withLivePolymarket } from "./polymarketLive";

/**
 * Pick of the Day live comparison is shown to EVERY visitor of the TEST site (Moose, 2026-11-19: "no log in"), never in
 * production. Prices are fetched at request time and never stored, recorded or graded. MODELROOM_POTD_LIVE=off disables it.
 */
export function potdLiveStatus(): { on: boolean; reason: string } {
  if (isProduction()) return { on: false, reason: "off in production" };
  if (process.env.MODELROOM_POTD_LIVE === "off") return { on: false, reason: "turned off on this site (MODELROOM_POTD_LIVE=off)" };
  return { on: true, reason: "" };
}
import { liveReason, strongestLiveProp, todaysGameIds, type LiveDiag, type LivePropPick } from "./potdPick";

/**
 * Pick of the Day, OWNER-ONLY live preview (TEST site): the strongest player prop on the published active board against
 * live Polymarket US prices, fetched at request time. Polymarket data is never stored, written to a file or shown to
 * anyone but the owner (polymarketLive.ts rules); this preview is NOT a recorded Pick of the Day and is never graded.
 */
export interface OwnerLive { pick: LivePropPick | null; checked: number; fetchedAt: string; reason: string; games: number; found: number; matched: number; diag: LiveDiag | null }

export async function ownerLivePropPick(league: League, now = new Date()): Promise<OwnerLive | null> {
  if (!potdLiveStatus().on) return null;
  const res = await loadPropsBoard(league);
  if (!res.ok) return { pick: null, checked: 0, fetchedAt: now.toISOString(), reason: `The ${league.toUpperCase()} props board isn't available: ${res.reason}`, games: 0, found: 0, matched: 0, diag: null };
  const ids = todaysGameIds(res.board as EnginePropsBoard, now);
  if (!ids.size) return { pick: null, checked: 0, fetchedAt: now.toISOString(), reason: "No games left today.", games: 0, found: 0, matched: 0, diag: null };
  try {
    const { board, info } = await withLivePolymarket(league, res.board, ids, now);
    const r = strongestLiveProp(league, board, ids);
    return { ...r, fetchedAt: info.fetchedAt, reason: r.pick ? "" : liveReason(info, r.diag), games: info.games, found: info.found, matched: info.matched };
  } catch (e) {
    return { pick: null, checked: 0, fetchedAt: now.toISOString(), reason: `Polymarket could not be reached (${(e as Error).message}).`, games: ids.size, found: 0, matched: 0, diag: null };
  }
}
