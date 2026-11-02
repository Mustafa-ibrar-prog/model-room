import { formatDateShort, formatNumber, formatSigned } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import { LockedCell, Panel, SourceStamp, Td, Th, Unavailable } from "@/components/ui/primitives";

/** Recent final scores, with the model's pre-game projection for each (Pro). */
export async function ResultsBoard({ league, limit = 12 }: { league: League; limit?: number }) {
  const viewer = await getViewer();
  const board = await getLeagueBoard(league, viewer.tier);
  if (!board.ok) return <Unavailable title="Results unavailable" body={board.reason} />;
  const games = board.recent.slice(0, limit);
  if (!games.length) return <Unavailable title="No recent results" body="No games have finished in the last few days." />;
  const pregame = board.recentPregame;

  return (
    <Panel>
      <div className="flex flex-wrap items-center gap-2 border-b border-navy-700 px-4 py-3">
        <h3 className="font-display text-lg font-600 text-ink">Recent results</h3>
        <SourceStamp>Results: {board.sources[0]}</SourceStamp>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-[0.95rem]">
          <caption className="sr-only">Recent final scores and the model&rsquo;s projection made before each game.</caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="sticky left-0 z-10 bg-navy-850">Game</Th>
              <Th className="text-right">Final</Th>
              <Th className="text-right">Model margin</Th>
              <Th className="text-right">Actual margin</Th>
              <Th className="text-right">Model total</Th>
              <Th className="text-right">Actual total</Th>
            </tr>
          </thead>
          <tbody>
            {games.map((g) => {
              const pre = isLocked(pregame) ? null : pregame[g.id];
              const r = g.result!;
              return (
                <tr key={g.id} className="border-t border-navy-700/70">
                  <Td className="sticky left-0 z-10 bg-navy-900">
                    <div className="text-[0.75rem] text-faint">{formatDateShort(g.gameDate)}</div>
                    <div className="font-display text-[1.05rem] font-600">
                      <span className={r.margin < 0 ? "text-ink" : "text-mute"}>{g.away.abbr}</span>
                      <span className="px-1 text-faint">@</span>
                      <span className={r.margin > 0 ? "text-ink" : "text-mute"}>{g.home.abbr}</span>
                    </div>
                  </Td>
                  <Td className="text-right text-ink/90">{r.awayScore}–{r.homeScore}</Td>
                  <Td className="text-right text-model">
                    {isLocked(pregame) ? <LockedCell requires={pregame.requires} /> : pre ? formatSigned(pre.margin) : null}
                  </Td>
                  <Td className="text-right text-ink/90">{formatSigned(r.margin, 0)}</Td>
                  <Td className="text-right text-model">
                    {isLocked(pregame) ? <LockedCell requires={pregame.requires} /> : pre ? formatNumber(pre.total) : null}
                  </Td>
                  <Td className="text-right text-ink/90">{r.total}</Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-navy-700 px-4 py-3 text-sm text-mute">
        Margins are home minus away. Model numbers for finished games come from a walk-forward run: each game uses only results from before its date.
      </p>
    </Panel>
  );
}
