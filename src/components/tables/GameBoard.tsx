import Link from "next/link";
import { formatEdge, formatNumber, formatSpread } from "@/lib/format";
import { FREE_EDGE_FINDER_LIMIT, canAccess } from "@/lib/entitlements";
import { getGameBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameProjection, type League } from "@/types/domain";
import { DemoStamp, Gated, LockIcon, Panel, Td, Th } from "@/components/ui/primitives";

/** Async server component. Render inside <Suspense>: it reads the viewer's plan. */
export async function GameBoard({ league, limit }: { league: League; limit?: number }) {
  const viewer = await getViewer();
  const board = await getGameBoard(league, viewer.tier);
  const rows = limit ? board.data.slice(0, limit) : board.data;
  const limitedEdges = !canAccess(viewer.tier, "games.edgeFinder.full");
  const notesLocked = rows.length > 0 && isLocked(rows[0].matchupNote);

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-navy-700 px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} game projections</h3>
          <DemoStamp />
        </div>
        <Legend />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[880px] border-collapse text-[0.95rem]">
          <caption className="sr-only">
            {league.toUpperCase()} demo game projections: market lines, model lines, edges and projected totals.
          </caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="sticky left-0 z-10 bg-navy-850">Matchup</Th>
              <Th className="text-right">Market spread</Th>
              <Th className="text-right">Model spread</Th>
              <Th>Spread edge</Th>
              <Th className="text-right">Market total</Th>
              <Th className="text-right">Model total</Th>
              <Th>Total edge</Th>
              <Th className="text-right">Projected score</Th>
              <Th className="text-right">Line move</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <GameRow key={g.id} g={g} />
            ))}
          </tbody>
        </table>
      </div>

      {(limitedEdges || notesLocked) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-navy-700 px-4 py-3 text-sm text-mute">
          <LockIcon className="h-4 w-4 text-edge" />
          <span>
            {limitedEdges
              ? `Free shows edges on the first ${FREE_EDGE_FINDER_LIMIT} games. Plus unlocks the full Edge Finder, projected scores, line movement and matchup breakdowns.`
              : "Matchup breakdowns are included with Plus."}
          </span>
          <Link href="/pricing" className="font-600 text-model hover:underline">
            Compare plans
          </Link>
        </div>
      )}
    </Panel>
  );
}

function GameRow({ g }: { g: GameProjection }) {
  return (
    <>
      <tr className="border-t border-navy-700/70 hover:bg-navy-850/60">
        <Td className="sticky left-0 z-10 bg-navy-900">
          <div className="text-[0.75rem] text-faint">{g.slot}</div>
          <div className="font-display text-[1.05rem] font-600 leading-tight">
            <span className="text-mute">{g.away.abbr}</span>
            <span className="px-1 text-faint">@</span>
            <span className="text-ink">{g.home.abbr}</span>
          </div>
        </Td>
        <Td className="text-right font-display text-lg font-600 text-market">{formatSpread(g.marketSpread)}</Td>
        <Td className="text-right font-display text-lg font-600 text-model">
          <Gated value={g.modelSpread}>{(v) => formatSpread(v)}</Gated>
        </Td>
        <Td>
          <Gated value={g.spreadEdge}>
            {(e) => <EdgeChip value={e} label={e > 0 ? g.home.abbr : g.away.abbr} />}
          </Gated>
        </Td>
        <Td className="text-right font-display text-lg font-600 text-market">{formatNumber(g.marketTotal)}</Td>
        <Td className="text-right font-display text-lg font-600 text-model">
          <Gated value={g.modelTotal}>{(v) => formatNumber(v)}</Gated>
        </Td>
        <Td>
          <Gated value={g.totalEdge}>{(e) => <EdgeChip value={e} label={e > 0 ? "Over" : "Under"} />}</Gated>
        </Td>
        <Td className="text-right text-ink/90">
          <Gated value={g.projectedScore}>
            {(s) => (
              <span>
                {formatNumber(s.away)}–{formatNumber(s.home)}
              </span>
            )}
          </Gated>
        </Td>
        <Td className="text-right text-mute">
          <Gated value={g.openingSpread}>
            {(open) => (
              <span title="Opening line to current line">
                {formatSpread(open)} <span className="text-faint">to</span> {formatSpread(g.marketSpread)}
              </span>
            )}
          </Gated>
        </Td>
      </tr>
      {!isLocked(g.matchupNote) && (
        <tr>
          <td colSpan={9} className="px-3 pb-3 pt-0 text-sm text-mute">
            <span className="sticky left-3">{g.matchupNote}</span>
          </td>
        </tr>
      )}
    </>
  );
}

/** Edge size sets emphasis: under 1 point reads as no edge. */
function EdgeChip({ value, label }: { value: number; label: string }) {
  const size = Math.abs(value);
  if (size < 1) return <span className="text-sm text-faint">No edge</span>;
  const strong = size >= 2;
  return (
    <span
      className={`inline-flex items-baseline gap-1.5 rounded-md px-2 py-0.5 font-display font-600 ${
        strong ? "bg-edge text-navy-950" : "bg-edge/15 text-edge"
      }`}
    >
      <span className="text-[0.95rem]">{label}</span>
      <span className="text-[1.05rem]">{formatEdge(size).replace("+", "")}</span>
    </span>
  );
}

function Legend() {
  return (
    <ul className="flex items-center gap-4 text-[0.8rem] text-mute" aria-label="Color key">
      <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-market" />Market</li>
      <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-model" />Model</li>
      <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-edge" />Edge</li>
    </ul>
  );
}
