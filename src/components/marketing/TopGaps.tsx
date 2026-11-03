import Link from "next/link";
import { favoredLine, formatNumber } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameView, type League, type TierId } from "@/types/domain";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell } from "@/components/ui/primitives";

type Gap = { league: League; g: GameView; kind: "Spread" | "Total"; size: number; model: string; market: string };

/** Where the model and the posted market line disagree most, across both sports. Real lines only. */
export async function TopGaps({ limit = 6 }: { limit?: number }) {
  const viewer = await getViewer();
  const boards = await Promise.all((["nfl", "nba"] as const).map(async (l) => [l, await getLeagueBoard(l, viewer.tier)] as const));
  const gaps: Gap[] = [];
  let locked: TierId | null = null;
  for (const [league, b] of boards) {
    if (!b.ok) continue;
    for (const g of b.upcoming) {
      if (isLocked(g.spreadEdge)) { locked = g.spreadEdge.requires; continue; }
      if (g.spreadEdge != null && g.market?.spread != null) {
        gaps.push({ league, g, kind: "Spread", size: Math.abs(g.spreadEdge), model: favoredLine(g.modelSpread, g.home.abbr, g.away.abbr).text, market: favoredLine(g.market.spread, g.home.abbr, g.away.abbr).text });
      }
      if (!isLocked(g.totalEdge) && g.totalEdge != null && g.market?.total != null) {
        gaps.push({ league, g, kind: "Total", size: Math.abs(g.totalEdge), model: formatNumber(g.modelTotal), market: formatNumber(g.market.total) });
      }
    }
  }
  gaps.sort((a, b) => b.size - a.size);
  if (!gaps.length) {
    return locked ? (
      <div className="flex items-center gap-2 rounded-lg border border-navy-700 bg-navy-900 p-4 text-sm text-mute">Model-vs-market gaps <LockedCell requires={locked} /></div>
    ) : (
      <p className="rounded-lg border border-navy-700 bg-navy-900 p-4 text-sm text-mute">No market lines posted for upcoming games yet.</p>
    );
  }
  return (
    <ul className="divide-y divide-navy-700/70 overflow-hidden rounded-lg border border-navy-700 bg-navy-900">
      {gaps.slice(0, limit).map((x) => (
        <li key={`${x.g.id}-${x.kind}`}>
          <Link href={`/${x.league}`} className="flex items-center gap-3 px-3 py-2.5 hover:bg-navy-850">
            <span className="w-9 font-mono text-[0.7rem] uppercase text-faint">{x.league}</span>
            <span className="flex items-center gap-1"><TeamBadge league={x.league} abbr={x.g.away.abbr} size="sm" /><span className="text-xs text-faint">@</span><TeamBadge league={x.league} abbr={x.g.home.abbr} size="sm" /></span>
            <span className="text-sm text-mute">{x.kind}</span>
            <span className="ml-auto font-mono text-sm text-model">{x.model}</span>
            <span className="font-mono text-sm text-market">{x.market}</span>
            <span className={`w-14 text-right font-mono text-sm ${x.size >= (x.kind === "Spread" ? 3 : 4) ? "text-edge" : "text-mute"}`}>{x.size.toFixed(1)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
