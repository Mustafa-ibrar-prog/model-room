import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { EnginePropsBoard } from "@/types/props";
import { loadPropsBoard, publishedDir } from "@/server/engine/board";
import { isProduction } from "@/lib/auth-config";
import { withLivePolymarket } from "./polymarketLive";
import { gameContext, liveReason, RELIABILITY, strongestLiveProp, todaysGameIds, type GameContext, type InjuryContext, type LiveDiag, type LivePropPick, type PlayerLogs, type Rejected } from "./potdPick";

async function readJson<T>(name: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), name), "utf8")) as T;
  } catch {
    return null;
  }
}

type GameBoard = { model?: { version?: string; uncertainty?: { margin_sigma?: number } }; upcoming?: { game_id: string; home: { abbr: string }; away: { abbr: string }; projection: { home_score: number; away_score: number; margin: number; total: number; pace?: number | null } }[] };
type Injuries = { players?: { team: string; player: string; status: string; kind?: string; source?: string; report_time?: string | null; game_date?: string }[] };

/** Game model context per game id (projected score, margin chances). Missing board = no context, never estimated. */
async function gameContexts(): Promise<Map<string, GameContext>> {
  const b = await readJson<GameBoard>("nba.json");
  const out = new Map<string, GameContext>();
  const sigma = b?.model?.uncertainty?.margin_sigma;
  if (!b?.upcoming || !sigma) return out;
  for (const g of b.upcoming) out.set(String(g.game_id), gameContext(g, sigma, b.model?.version ?? "?"));
  return out;
}

const LISTED = new Set(["out", "doubtful", "questionable"]);
/** Both teams' Out / Doubtful / Questionable entries from the live report (official first, ESPN otherwise). */
async function injuryLookup(): Promise<(team: string, opp: string) => InjuryContext | null> {
  const r = await readJson<Injuries>("injuries_live_nba.json");
  const rows = (r?.players ?? []).filter((x) => LISTED.has((x.status ?? "").toLowerCase()));
  return (team, opp) => {
    if (!r) return null;
    const pick = (t: string) => {
      const own = rows.filter((x) => x.team === t);
      const off = own.filter((x) => x.kind === "official");
      return (off.length ? off : own).map((x) => ({ name: x.player, status: x.status }));
    };
    const any = rows.find((x) => x.team === team || x.team === opp);
    return { source: any?.kind === "official" ? "NBA official injury report" : "ESPN injury report", reportTime: any?.report_time ?? null, team: pick(team), opp: pick(opp) };
  };
}

/** Box-score game logs for the hit-frequency context (missing file = no context shown, never estimated). */
async function playerLogs(): Promise<PlayerLogs | null> {
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), "nba_player_logs.json"), "utf8")) as PlayerLogs;
  } catch {
    return null;
  }
}

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
  pick: LivePropPick | null; picks: LivePropPick[]; checked: number; fetchedAt: string; reason: string; games: number; found: number; matched: number;
  diag: LiveDiag | null; rejected: Rejected[]; modelVersion: string | null; boardAt: string | null;
}

/** NBA only. Uses the published ACTIVE props board (never a shadow version); Polymarket data is never stored. */
export async function livePropPick(now = new Date()): Promise<LiveResult | null> {
  if (!potdLiveStatus().on) return null;
  const empty = { pick: null, picks: [] as LivePropPick[], checked: 0, fetchedAt: now.toISOString(), games: 0, found: 0, matched: 0, diag: null, rejected: [], modelVersion: null, boardAt: null };
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
    const r = strongestLiveProp(priced, ids, await playerLogs());
    const [games, inj] = await Promise.all([gameContexts(), injuryLookup()]);
    for (const p of r.picks) {
      p.game = games.get(String(p.gameId)) ?? null;
      p.injuries = inj(p.team, p.opp);
    }
    return { ...r, fetchedAt: info.fetchedAt, reason: r.pick ? "" : liveReason(info, r.diag), games: info.games, found: info.found, matched: info.matched, modelVersion: version, boardAt };
  } catch (e) {
    return { ...empty, games: ids.size, modelVersion: version, boardAt, reason: `Polymarket could not be reached (${(e as Error).message}).` };
  }
}
