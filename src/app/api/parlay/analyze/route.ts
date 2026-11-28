import { liveMarketsOn } from "@/server/markets/polymarketLive";
import { NextResponse, type NextRequest } from "next/server";
import { explainParlay } from "@/server/parlay/analyze";
import { buildEvidence, loadSources } from "@/server/ai/evidence";
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
  // Evidence is built for every leg whether or not the AI runs (it's Model Room's own data, shown as is).
  const evidence = price.ok ? buildEvidence(price.legs, await loadSources([...new Set(price.legs.map((l) => l.league))])) : {};
  const ai = await explainParlay(price, evidence, v);
  return withVisitor(NextResponse.json({ price, ai, evidence }, { headers: noStore }), v);
}
