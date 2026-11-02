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
