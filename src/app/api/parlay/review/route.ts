import { liveMarketsOn } from "@/server/markets/polymarketLive";
import { NextResponse, type NextRequest } from "next/server";
import { loadSources } from "@/server/ai/evidence";
import { reviewWithAi } from "@/server/parlay/analyze";
import { getCatalog } from "@/server/parlay/legs";
import { noStore, notFound, parlayEnabled, visitor, withVisitor } from "@/server/parlay/request";
import { reviewBoards, reviewPack } from "@/server/parlay/review";

/**
 * Evidence review across the NBA and NFL boards (TEST only). GET: the candidates and their evidence counts (fixed
 * rules, no AI). POST: the same plus one Gemini review (cached 6 h, counted against the daily caps). Separate from the
 * model's ranking and from Picks to consider; never creates picks.
 */
async function build() {
  const now = new Date();
  const live = liveMarketsOn();
  const catalogs = await Promise.all([getCatalog("nba", now, { live }), getCatalog("nfl", now, { live })]);
  const src = await loadSources(["nba", "nfl"]);
  const r = reviewBoards(catalogs, src);
  return { ...r, pack: reviewPack(r.items, r.evidence) };
}

export async function GET() {
  if (!parlayEnabled()) return notFound();
  const r = await build();
  return NextResponse.json({ items: r.items, evidence: r.evidence, scanned: r.scanned }, { headers: noStore });
}

export async function POST(req: NextRequest) {
  if (!parlayEnabled()) return notFound();
  const r = await build();
  const v = visitor(req);
  const ai = await reviewWithAi(r.pack, v);
  return withVisitor(NextResponse.json({ items: r.items, evidence: r.evidence, scanned: r.scanned, ai }, { headers: noStore }), v);
}
