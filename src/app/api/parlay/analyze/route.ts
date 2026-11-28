import { liveMarketsOn } from "@/server/markets/polymarketLive";
import { NextResponse, type NextRequest } from "next/server";
import { explainParlay } from "@/server/parlay/analyze";
import { loadTable } from "@/server/parlay/correlations";
import { priceParlay } from "@/server/parlay/price";
import { catalogsFor, noStore, notFound, parlayEnabled, readLegIds, visitor, withVisitor } from "@/server/parlay/request";

/**
 * POST /api/parlay/analyze {legs: string[]}: "Analyze My Parlay" (TEST only). Re-prices on the server, then asks Gemini to
 * explain those numbers. Runs only when the button is pressed; the numbers come back even when AI is unavailable.
 */
export async function POST(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const ids = await readLegIds(req);
  if (!ids) return NextResponse.json({ error: "Send 1 to 10 leg ids." }, { status: 400 });
  const catalogs = await catalogsFor(ids, new Date(), liveMarketsOn());
  const price = priceParlay(ids, catalogs, loadTable());
  const v = visitor(req);
  const ai = await explainParlay(price, catalogs, v);
  return withVisitor(NextResponse.json({ price, ai }, { headers: noStore }), v);
}
