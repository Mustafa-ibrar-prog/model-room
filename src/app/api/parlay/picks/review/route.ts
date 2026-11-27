import { NextResponse, type NextRequest } from "next/server";
import { reviewPicks } from "@/server/parlay/analyze";
import { discoverPicks } from "@/server/parlay/discover";
import { getCatalog } from "@/server/parlay/legs";
import { noStore, notFound, parlayEnabled, visitor, withVisitor } from "@/server/parlay/request";

/** POST /api/parlay/picks/review: Gemini explains the statistical list (same list, same order; it can't add picks). */
export async function POST(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const catalogs = await Promise.all([getCatalog("nba"), getCatalog("nfl")]);
  const picks = discoverPicks(catalogs);
  const v = visitor(req);
  const ai = await reviewPicks(picks, catalogs, v);
  return withVisitor(NextResponse.json({ picks, ai }, { headers: noStore }), v);
}
