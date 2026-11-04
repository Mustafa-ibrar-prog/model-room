import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { connection } from "next/server";
import { cache } from "react";
import type { League } from "@/types/domain";
import type { EngineBoard } from "@/types/engine";
import type { EnginePropsBoard } from "@/types/props";

/**
 * Reads the board file a Python engine published. Server only: the files sit
 * outside public/ and are never served directly.
 *
 * Location: MODELROOM_PUBLISHED_DIR, else <repo>/modeling/data/published.
 */
export function publishedDir(): string {
  return process.env.MODELROOM_PUBLISHED_DIR ?? path.join(process.cwd(), "modeling", "data", "published");
}

export type BoardResult = { ok: true; board: EngineBoard } | { ok: false; reason: string };

const SUPPORTED_SCHEMA = 1;

/** Cached per request, so several components on one page share a single read. */
export const loadBoard = cache(async function loadBoard(league: League): Promise<BoardResult> {
  await connection(); // read per request, never baked into the build
  const file = path.join(publishedDir(), `${league}.json`);
  let text: string;
  try {
    text = await readFile(file, "utf8");
  } catch {
    return {
      ok: false,
      reason: `No ${league.toUpperCase()} projections have been generated yet. Run: python -m modelroom ${league} project`,
    };
  }
  try {
    const board = JSON.parse(text) as EngineBoard;
    if (board.schema_version !== SUPPORTED_SCHEMA) {
      return { ok: false, reason: `Projection file uses schema ${board.schema_version}; this site reads schema ${SUPPORTED_SCHEMA}.` };
    }
    if (board.league !== league) {
      return { ok: false, reason: `Projection file is for ${board.league}, expected ${league}.` };
    }
    return { ok: true, board };
  } catch {
    return { ok: false, reason: `The ${league.toUpperCase()} projection file could not be read. Re-run the model.` };
  }
});

export type PropsBoardResult = { ok: true; board: EnginePropsBoard } | { ok: false; reason: string };

/** The player-prop board (<league>_props.json). Same rules as loadBoard. */
export const loadPropsBoard = cache(async function loadPropsBoard(league: League): Promise<PropsBoardResult> {
  await connection();
  const file = path.join(publishedDir(), `${league}_props.json`);
  let text: string;
  try {
    text = await readFile(file, "utf8");
  } catch {
    return {
      ok: false,
      reason:
        league === "nfl"
          ? "No NFL prop projections have been generated yet. Run: python -m modelroom nfl props"
          : "NBA player props aren't built yet.",
    };
  }
  try {
    const board = JSON.parse(text) as EnginePropsBoard;
    if (board.schema_version !== SUPPORTED_SCHEMA || board.kind !== "player_props" || board.league !== league) {
      return { ok: false, reason: `The ${league.toUpperCase()} prop file isn't in a format this site reads. Re-run the model.` };
    }
    return { ok: true, board };
  } catch {
    return { ok: false, reason: `The ${league.toUpperCase()} prop file could not be read. Re-run the model.` };
  }
});

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** A published history file (data/published/history/<league>/<date|index>.json). */
export async function loadHistoryFile<T>(league: League, name: string): Promise<T | null> {
  await connection();
  if (name !== "index" && !DATE_RE.test(name)) return null; // never build a path from arbitrary input
  try {
    const text = await readFile(path.join(publishedDir(), "history", league, `${name}.json`), "utf8");
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export async function loadPerformanceFile<T>(league: League): Promise<T | null> {
  await connection();
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), `performance_${league}.json`), "utf8")) as T;
  } catch {
    return null;
  }
}

/** data/published/market_results_<league>.json: market-settled grading (publishable providers only). */
export async function loadMarketResultsFile<T>(league: League): Promise<T | null> {
  await connection();
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), `market_results_${league}.json`), "utf8")) as T;
  } catch {
    return null;
  }
}

export interface RefreshStatus {
  last_success: { slot: string; at: string; note: string | null } | null;
  recent_failures: { slot: string; at: string; note: string | null }[];
  schedule: string;
}

/** The refresh log's summary (written by every scheduled refresh). Null before the first logged run. */
export async function loadRefreshStatus(): Promise<RefreshStatus | null> {
  await connection();
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), "refresh_status.json"), "utf8")) as RefreshStatus;
  } catch {
    return null;
  }
}


export interface LiveInjuryRow {
  team: string;
  player: string;
  player_id: string;
  position: string | null;
  status: string;
  raw_status: string | null;
  source: string;
  kind: "official" | "report";
  report_time: string | null;
  detail: string | null;
  comment: string | null;
  current: boolean;
  stale: boolean;
  stale_reason: string | null;
  conflict: string | null;
  late_scratch: boolean;
  long_term: boolean;
  restriction: boolean;
  team_report?: string;
}

export interface LiveInjuries {
  league: string;
  generated_at: string;
  sources: Record<string, { ok: boolean; rows?: number; error?: string; report_time?: string; url?: string }>;
  filings: { game_date: string; team: string; submitted: boolean }[];
  conflicts: number;
  players: LiveInjuryRow[];
}

/** The injury refresh's combined feed (test site). Null when no feed has been fetched for the league. */
export async function loadLiveInjuries(league: League): Promise<LiveInjuries | null> {
  await connection();
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), `injuries_live_${league}.json`), "utf8")) as LiveInjuries;
  } catch {
    return null;
  }
}
