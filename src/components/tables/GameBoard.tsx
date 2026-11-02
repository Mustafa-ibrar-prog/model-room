import Link from "next/link";
import { FREE_EDGE_FINDER_LIMIT, canAccess } from "@/lib/entitlements";
import { favoredLine, formatKickoff, formatNumber, formatPct, formatSigned } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameView, type League } from "@/types/domain";
import { Gated, LockIcon, Missing, Panel, SourceStamp, Td, Th, Unavailable } from "@/components/ui/primitives";

/** Upcoming games with model projections. Async server component; render inside <Suspense>. */
export async function GameBoard({ league, limit, withinHours }: { league: League; limit?: number; withinHours?: number }) {
  const viewer = await getViewer();
  const board = await getLeagueBoard(league, viewer.tier);
  if (!board.ok) return <Unavailable title={`${league.toUpperCase()} projections unavailable`} body={board.reason} />;

  const firstStart = board.upcoming[0]?.startTime ? Date.parse(board.upcoming[0].startTime) : null;
  const windowed = withinHours && firstStart !== null
    ? board.upcoming.filter((g) => g.startTime !== null && Date.parse(g.startTime) - firstStart <= withinHours * 3600_000)
    : board.upcoming;
  const games = limit ? windowed.slice(0, limit) : windowed;
  if (!games.length) {
    return (
      <Unavailable
        title={`No ${league.toUpperCase()} games in the next window`}
        body="The schedule has no games in the projection window. Check back after the next model run."
      />
    );
  }
  const limitedEdges = !canAccess(viewer.tier, "games.edgeFinder.full");
  const scoresLocked = isLocked(games[0].projectedScore);

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-navy-700 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-display text-lg font-600 text-ink">
            {league.toUpperCase()} {board.week ? `week ${board.week} ` : ""}projections
          </h3>
          <SourceStamp>Model {board.model.version}</SourceStamp>
        </div>
        <Legend />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] border-collapse text-[0.95rem]">
          <caption className="sr-only">
            {league.toUpperCase()} upcoming games: model line and total, projected score, win probability, and the market line where one is connected.
          </caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="sticky left-0 z-10 bg-navy-850">Game</Th>
              <Th>Model line</Th>
              <Th className="text-right">Model total</Th>
              <Th className="text-right">Projected score</Th>
              <Th className="text-right">Win probability</Th>
              <Th>Market line</Th>
              <Th className="text-right">Market total</Th>
              <Th>Edge</Th>
            </tr>
          </thead>
          <tbody>
            {games.map((g) => (
              <GameRow key={g.id} g={g} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-navy-700 px-4 py-3 text-sm text-mute">
        <span>
          Lines are shown for the favored team. {board.market.connected ? "" : `${board.market.note ?? "No market lines connected."} `}
        </span>
        {(limitedEdges || scoresLocked) && (
          <span className="flex items-center gap-1.5">
            <LockIcon className="h-4 w-4 text-edge" />
            {limitedEdges
              ? `Free shows edges on the first ${FREE_EDGE_FINDER_LIMIT} games with a market line. Plus adds every edge, projected scores and win probabilities.`
              : "Projected scores and win probabilities are included with Plus."}
            <Link href="/pricing" className="font-600 text-model hover:underline">
              Compare plans
            </Link>
          </span>
        )}
      </div>
    </Panel>
  );
}

function GameRow({ g }: { g: GameView }) {
  const model = favoredLine(g.modelSpread, g.home.abbr, g.away.abbr);
  const market = g.market?.spread != null ? favoredLine(g.market.spread, g.home.abbr, g.away.abbr) : null;
  const notes = [
    g.rest.homeB2b && `${g.home.abbr} on a back-to-back`,
    g.rest.awayB2b && `${g.away.abbr} on a back-to-back`,
    g.neutral && "Neutral site",
    g.quarterbacks && (g.quarterbacks.away || g.quarterbacks.home) && `QBs: ${g.quarterbacks.away ?? "TBD"} at ${g.quarterbacks.home ?? "TBD"}`,
  ].filter(Boolean);

  return (
    <tr className="border-t border-navy-700/70 align-top hover:bg-navy-850/60">
      <Td className="sticky left-0 z-10 bg-navy-900">
        <div className="text-[0.75rem] text-faint">{formatKickoff(g.startTime)}</div>
        <div className="font-display text-[1.05rem] font-600 leading-tight">
          <span className="text-mute" title={g.away.name}>{g.away.abbr}</span>
          <span className="px-1 text-faint">@</span>
          <span className="text-ink" title={g.home.name}>{g.home.abbr}</span>
        </div>
        {notes.length > 0 && <div className="mt-0.5 max-w-[15rem] whitespace-normal text-[0.75rem] text-faint">{notes.join(". ")}</div>}
      </Td>
      <Td className="font-display text-lg font-600 text-model">{model.text}</Td>
      <Td className="text-right font-display text-lg font-600 text-model">{formatNumber(g.modelTotal)}</Td>
      <Td className="text-right text-ink/90">
        <Gated value={g.projectedScore}>
          {(s) => (
            <span title={`${g.away.abbr} ${formatNumber(s.away)}, ${g.home.abbr} ${formatNumber(s.home)}`}>
              {formatNumber(s.away)}–{formatNumber(s.home)}
            </span>
          )}
        </Gated>
      </Td>
      <Td className="text-right">
        <Gated value={g.winProbability}>
          {(p) => (
            <div>
              <div className="text-ink/90">
                <span className={p.away > p.home ? "font-600 text-ink" : "text-mute"}>{g.away.abbr} {formatPct(p.away)}</span>
                <span className="px-1 text-faint">/</span>
                <span className={p.home >= p.away ? "font-600 text-ink" : "text-mute"}>{g.home.abbr} {formatPct(p.home)}</span>
              </div>
              {!isLocked(g.probabilityEdge) && g.probabilityEdge && (
                <div className="text-[0.72rem] text-market" title="No-vig probability implied by the moneylines">
                  Market {g.home.abbr} {formatPct(g.probabilityEdge.homeMarket)} (model {formatSigned(g.probabilityEdge.homeDiff * 100, 0)} pts)
                </div>
              )}
              <Gated value={g.ranges}>
                {(r) =>
                  r.margin ? (
                    <div className="text-[0.72rem] text-faint" title="80% of outcomes in out-of-sample testing fell within this margin range">
                      80% margin {formatSigned(r.margin[0], 0)} to {formatSigned(r.margin[1], 0)}
                    </div>
                  ) : null
                }
              </Gated>
            </div>
          )}
        </Gated>
      </Td>
      <Td className="font-display text-lg font-600 text-market">
        {market ? market.text : <Missing title="No market line for this game" />}
      </Td>
      <Td className="text-right font-display text-lg font-600 text-market">
        {g.market?.total != null ? formatNumber(g.market.total) : <Missing title="No market total for this game" />}
      </Td>
      <Td>
        <EdgeCell g={g} />
      </Td>
    </tr>
  );
}

function EdgeCell({ g }: { g: GameView }) {
  if (!g.market || (g.market.spread == null && g.market.total == null)) return <Missing title="No market line, so no edge" />;
  if (isLocked(g.spreadEdge)) return <Gated value={g.spreadEdge}>{() => null}</Gated>;
  const spread = g.spreadEdge;
  const total = isLocked(g.totalEdge) ? null : g.totalEdge;
  return (
    <div className="flex flex-col items-start gap-1">
      {spread != null && <EdgeChip value={spread} label={spread > 0 ? g.home.abbr : g.away.abbr} />}
      {total != null && <EdgeChip value={total} label={total > 0 ? "Over" : "Under"} />}
    </div>
  );
}

/** Edge size sets emphasis: under 1 point reads as no edge. */
function EdgeChip({ value, label }: { value: number; label: string }) {
  const size = Math.abs(value);
  if (size < 1) return <span className="text-sm text-faint">No edge</span>;
  const strong = size >= 2;
  return (
    <span
      className={`inline-flex items-baseline gap-1.5 rounded-md px-2 py-0.5 font-display font-600 ${strong ? "bg-edge text-navy-950" : "bg-edge/15 text-edge"}`}
      title="Points between the model and the market"
    >
      <span className="text-[0.95rem]">{label}</span>
      <span className="text-[1.05rem]">{size.toFixed(1)}</span>
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
