import { formatNumber, formatSigned } from "@/lib/format";
import { getRatings } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import { LockedCell, Missing, Panel, SourceStamp, Td, Th, Unavailable } from "@/components/ui/primitives";

/** Team power ratings from the league engine. Overall is on every plan; components are Pro. */
export async function RatingsBoard({ league, limit }: { league: League; limit?: number }) {
  const viewer = await getViewer();
  const res = await getRatings(league, viewer.tier);
  if (!res.ok) return <Unavailable title={`${league.toUpperCase()} ratings unavailable`} body={res.reason} />;
  const rows = limit ? res.rows.slice(0, limit) : res.rows;
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.overall)), 1);
  const first = rows[0];
  const componentHeads = first && !isLocked(first.components) ? first.components : null;
  const lockedTier = first && isLocked(first.components) ? first.components.requires : null;

  return (
    <Panel>
      <div className="flex flex-wrap items-center gap-2 border-b border-navy-700 px-4 py-3">
        <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} power ratings, {res.seasonLabel}</h3>
        <SourceStamp>Model {res.modelVersion}</SourceStamp>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] border-collapse text-[0.95rem]">
          <caption className="sr-only">{league.toUpperCase()} team ratings: {first?.overallUnit}.</caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="w-12 text-right">Rank</Th>
              <Th className="sticky left-0 z-10 bg-navy-850">Team</Th>
              <Th className="w-[28%]">Overall ({first?.overallUnit})</Th>
              {componentHeads
                ? componentHeads.map((c) => <Th key={c.key} className="text-right">{c.label}</Th>)
                : <Th className="text-right">Breakdown</Th>}
              <Th className="text-right">Games</Th>
              <Th className="text-right">Avg margin</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const pct = (Math.abs(r.overall) / maxAbs) * 50;
              const positive = r.overall >= 0;
              return (
                <tr key={r.team.abbr} className="border-t border-navy-700/70">
                  <Td className="text-right font-display text-lg font-600 text-faint">{r.rank}</Td>
                  <Td className="sticky left-0 z-10 bg-navy-900">
                    <span className="font-display text-[1.05rem] font-600 text-ink">{r.team.abbr}</span>
                    <span className="ml-2 hidden text-sm text-mute sm:inline">{r.team.name}</span>
                  </Td>
                  <Td>
                    <div className="flex items-center gap-3">
                      <div className="relative h-2 flex-1 rounded-full bg-navy-800" aria-hidden="true">
                        <div className="absolute left-1/2 top-[-3px] h-[14px] w-px bg-navy-600" />
                        <div
                          className={`absolute top-0 h-2 rounded-full ${positive ? "bg-model" : "bg-market"}`}
                          style={positive ? { left: "50%", width: `${pct}%` } : { right: "50%", width: `${pct}%` }}
                        />
                      </div>
                      <span className={`w-14 text-right font-display text-lg font-600 ${positive ? "text-model" : "text-market"}`}>
                        {formatSigned(r.overall)}
                      </span>
                    </div>
                  </Td>
                  {isLocked(r.components) ? (
                    <Td className="text-right"><LockedCell requires={r.components.requires} /></Td>
                  ) : (
                    r.components.map((c) => (
                      <Td key={c.key} className="text-right">
                        {c.value == null ? <Missing /> : formatNumber(c.value, Math.abs(c.value) < 1 ? 3 : 1)}
                      </Td>
                    ))
                  )}
                  <Td className="text-right text-mute">{r.games}</Td>
                  <Td className="text-right text-mute">{r.avgMargin == null ? <Missing /> : formatSigned(r.avgMargin)}</Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {lockedTier && (
        <p className="border-t border-navy-700 px-4 py-3 text-sm text-mute">Offense, defense, pace and schedule breakdowns are included with Pro.</p>
      )}
    </Panel>
  );
}
