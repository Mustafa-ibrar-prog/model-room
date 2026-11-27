import { NextResponse, type NextRequest } from "next/server";
import { loadTable } from "@/server/parlay/correlations";
import { priceParlay } from "@/server/parlay/price";
import { catalogsFor, noStore, notFound, parlayEnabled, readLegIds } from "@/server/parlay/request";

/** POST /api/parlay/price {legs: string[]}: the engine's numbers only, no AI (TEST only). */
export async function POST(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const ids = await readLegIds(req);
  if (!ids) return NextResponse.json({ error: "Send 1 to 10 leg ids." }, { status: 400 });
  const price = priceParlay(ids, await catalogsFor(ids), loadTable());
  return NextResponse.json(price, { headers: noStore });
}
