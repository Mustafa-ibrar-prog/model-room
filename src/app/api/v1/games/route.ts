import { NextResponse, type NextRequest } from "next/server";
import { getGameBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";

/**
 * GET /api/v1/games?league=nfl|nba
 *
 * Same gating as the pages: the response only contains fields the caller's
 * plan includes. Locked fields come back as { locked: true, requires }.
 */
export async function GET(request: NextRequest) {
  const league = request.nextUrl.searchParams.get("league");
  if (league !== "nfl" && league !== "nba") {
    return NextResponse.json({ error: "Set league to nfl or nba." }, { status: 400 });
  }
  const viewer = await getViewer();
  const board = await getGameBoard(league, viewer.tier);
  return NextResponse.json(board, { headers: { "Cache-Control": "private, no-store" } });
}
