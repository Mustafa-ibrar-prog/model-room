import { liveMarketsOn } from "@/server/markets/polymarketLive";
import { NextResponse, type NextRequest } from "next/server";
import { getCatalog } from "@/server/parlay/legs";
import { leagueParam, noStore, notFound, parlayEnabled } from "@/server/parlay/request";

/**
 * GET /api/parlay/legs?league=nba|nfl&game=ID   one card per player per stat and per game market, plus the listed legs
 * GET /api/parlay/legs?league=nba|nfl&id=LEGID  one leg (a card's selected side and threshold), derived on the server
 * TEST only.
 */
export async function GET(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const sp = req.nextUrl.searchParams;
  const league = leagueParam(sp.get("league"));
  const id = sp.get("id");
  const game = sp.get("game") ?? "";
  if (!league) return NextResponse.json({ error: "Set league." }, { status: 400 });
  if (id !== null) {
    if (!/^[A-Za-z0-9_.~\-]{1,160}$/.test(id)) return NextResponse.json({ error: "Bad leg." }, { status: 400 });
    const c = await getCatalog(league, new Date(), { live: liveMarketsOn(), games: [id.split("~")[1] ?? ""] });
    const leg = c.resolve(id);
    if (!leg) return NextResponse.json({ error: "That selection isn't available." }, { status: 404, headers: noStore });
    return NextResponse.json({ leg: leg.option }, { headers: noStore });
  }
  if (!/^[A-Za-z0-9_]{1,40}$/.test(game)) return NextResponse.json({ error: "Set league and game." }, { status: 400 });
  const c = await getCatalog(league, new Date(), { live: liveMarketsOn(), games: [game] });
  const legs = c.byGame.get(game);
  if (!legs) return NextResponse.json({ error: "That game isn't available (it may have started)." }, { status: 404, headers: noStore });
  return NextResponse.json({ game: c.games.find((g) => g.gameId === game), legs, cards: c.cards.get(game) ?? { props: [], games: [] },
    injuries: c.injuries.get(game) ?? [] }, { headers: noStore });
}
