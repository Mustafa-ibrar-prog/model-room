import { NextResponse, type NextRequest } from "next/server";
import { getCatalog } from "@/server/parlay/legs";
import { leagueParam, noStore, notFound, parlayEnabled } from "@/server/parlay/request";

/** GET /api/parlay/games?league=nba|nfl: upcoming games the Parlay Builder can use (TEST only). */
export async function GET(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const league = leagueParam(req.nextUrl.searchParams.get("league"));
  if (!league) return NextResponse.json({ error: "Set league to nba or nfl." }, { status: 400 });
  const c = await getCatalog(league);
  return NextResponse.json({ games: c.games, asOf: c.asOf }, { headers: noStore });
}
