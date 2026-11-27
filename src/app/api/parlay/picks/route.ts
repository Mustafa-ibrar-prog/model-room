import { NextResponse } from "next/server";
import { discoverPicks } from "@/server/parlay/discover";
import { getCatalog } from "@/server/parlay/legs";
import { noStore, notFound, parlayEnabled } from "@/server/parlay/request";
import { loadValidation } from "@/server/parlay/validation";

/** GET /api/parlay/picks: statistical picks to consider, both leagues (TEST only). No AI here. */
export async function GET() {
  if (!parlayEnabled()) return notFound();
  const catalogs = await Promise.all([getCatalog("nba"), getCatalog("nfl")]);
  return NextResponse.json({ picks: discoverPicks(catalogs), history: loadValidation()?.discovery ?? null }, { headers: noStore });
}
