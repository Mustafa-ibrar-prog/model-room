import { NextResponse, type NextRequest } from "next/server";
import { discoverPicks } from "@/server/parlay/discover";
import { getCatalog } from "@/server/parlay/legs";
import { noStore, notFound, privateRequest, parlayEnabled } from "@/server/parlay/request";
import { loadValidation } from "@/server/parlay/validation";

/** GET /api/parlay/picks: statistical picks to consider, both leagues (TEST only). No AI here. */
export async function GET(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const live = privateRequest(req);
  const catalogs = await Promise.all([getCatalog("nba", new Date(), { live }), getCatalog("nfl", new Date(), { live })]);
  return NextResponse.json({ picks: discoverPicks(catalogs), history: loadValidation()?.discovery ?? null }, { headers: noStore });
}
