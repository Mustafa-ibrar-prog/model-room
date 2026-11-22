import "server-only";
import type { EnginePropsBoard } from "@/types/props";
import { loadPropsBoard } from "@/server/engine/board";
import { isProduction } from "@/lib/auth-config";
import { withLivePolymarket } from "./polymarketLive";
import { liveReason, RELIABILITY, strongestLiveProp, todaysGameIds, type LiveDiag, type LivePropPick, type Rejected } from "./potdPick";

/**
 * NBA Pick of the Day live preview: shown to EVERY visitor of the TEST site (Moose, 2026-11-19: "no log in"), never in
 * production. Prices are fetched at request time and never stored, recorded or graded. MODELROOM_POTD_LIVE=off disables it.
 */
export function potdLiveStatus(): { on: boolean; reason: string } {
  if (isProduction()) return { on: false, reason: "off in production" };
  if (process.env.MODELROOM_POTD_LIVE === "off") return { on: false, reason: "turned off on this site (MODELROOM_POTD_LIVE=off)" };
  return { on: true, reason: "" };
}

export interface LiveResult {
  pick: LivePropPick | null; checked: number; fetchedAt: string; reason: string; games: number; found: number; matched: number;
  diag: LiveDiag | null; rejected: Rejected[]; modelVersion: string | null; boardAt: string | null;
}

/** NBA only. Uses the published ACTIVE props board (never a shadow version); Polymarket data is never stored. */
export async function livePropPick(now = new Date()): Promise<LiveResult | null> {
  if (!potdLiveStatus().on) return null;
  const empty = { pick: null, checked: 0, fetchedAt: now.toISOString(), games: 0, found: 0, matched: 0, diag: null, rejected: [], modelVersion: null, boardAt: null };
  const res = await loadPropsBoard("nba");
  if (!res.ok) return { ...empty, reason: `The NBA props board isn't available: ${res.reason}` };
  const board = res.board as EnginePropsBoard;
  const version = board.model.version;
  const boardAt = (board as unknown as { generated_at?: string }).generated_at ?? null;
  if (version !== RELIABILITY.model) {
    return { ...empty, modelVersion: version, boardAt, reason: `The reliability adjustment is fitted for model ${RELIABILITY.model}; model ${version} needs its own fit and approval first.` };
  }
  const ids = todaysGameIds(board, now);
  if (!ids.size) return { ...empty, modelVersion: version, boardAt, reason: "No NBA games left today." };
  try {
    const { board: priced, info } = await withLivePolymarket("nba", board, ids, now);
    const r = strongestLiveProp(priced, ids);
    return { ...r, fetchedAt: info.fetchedAt, reason: r.pick ? "" : liveReason(info, r.diag), games: info.games, found: info.found, matched: info.matched, modelVersion: version, boardAt };
  } catch (e) {
    return { ...empty, games: ids.size, modelVersion: version, boardAt, reason: `Polymarket could not be reached (${(e as Error).message}).` };
  }
}
