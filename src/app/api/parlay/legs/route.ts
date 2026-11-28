import { liveMarketsOn } from "@/server/markets/polymarketLive";
import { NextResponse, type NextRequest } from "next/server";
import { getCatalog } from "@/server/parlay/legs";
import { leagueParam, noStore, notFound, parlayEnabled } from "@/server/parlay/request";

/** GET /api/parlay/legs?league=nba|nfl&game=ID: every leg offered for one game (TEST only). */
export async function GET(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const league = leagueParam(req.nextUrl.searchParams.get("league"));
  const game = req.nextUrl.searchParams.get("game") ?? "";
  if (!league || !/^[A-Za-z0-9_]{1,40}$/.test(game)) return NextResponse.json({ error: "Set league and game." }, { status: 400 });
  const c = await getCatalog(league, new Date(), { live: liveMarketsOn() });
  const legs = c.byGame.get(game);
  if (!legs) return NextResponse.json({ error: "That game isn't available (it may have started)." }, { status: 404, headers: noStore });
  return NextResponse.json({ game: c.games.find((g) => g.gameId === game), legs, injuries: c.injuries.get(game) ?? [] }, { headers: noStore });
}
