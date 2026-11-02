import { formatEdge, formatNumber } from "@/lib/format";
import { getRatings } from "@/server/data";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";
import { DemoStamp, Gated, Panel, Td, Th } from "@/components/ui/primitives";

/** Team power ratings. Overall is open; splits are Pro (advanced analytics). */
export async function RatingsBoard({ league }: { league: League }) {
  const viewer = await getViewer();
  const { data } = await getRatings(league, viewer.tier);
  const maxAbs = Math.max(...data.map((r) => Math.abs(r.overall)), 1);
  const offLabel = league === "nba" ? "Off. rating" : "Offense";
  const defLabel = league === "nba" ? "Def. rating" : "Defense";

  return (
    <Panel>
      <div className="flex items-center gap-2 border-b border-navy-700 px-4 py-3">
        <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} power ratings</h3>
        <DemoStamp />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-[0.95rem]">
          <caption className="sr-only">
            {league.toUpperCase()} demo power ratings in points versus an average team.
          </caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="w-12 text-right">Rank</Th>
              <Th className="sticky left-0 z-10 bg-navy-850">Team</Th>
              <Th className="w-[34%]">Overall (pts vs average)</Th>
              <Th className="text-right">{offLabel}</Th>
              <Th className="text-right">{defLabel}</Th>
              <Th className="text-right">Pace</Th>
              <Th className="text-right">Schedule</Th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => {
              const pct = (Math.abs(r.overall) / maxAbs) * 50;
              const positive = r.overall >= 0;
              return (
                <tr key={r.team.id} className="border-t border-navy-700/70">
                  <Td className="text-right font-display text-lg font-600 text-faint">{r.rank}</Td>
                  <Td className="sticky left-0 z-10 bg-navy-900">
                    <span className="font-display text-[1.05rem] font-600 text-ink">{r.team.abbr}</span>
                    <span className="ml-2 hidden text-sm text-mute sm:inline">
                      {r.team.city} {r.team.name}
                    </span>
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
                      <span className={`w-12 text-right font-display text-lg font-600 ${positive ? "text-model" : "text-market"}`}>
                        {formatEdge(r.overall)}
                      </span>
                    </div>
                  </Td>
                  <Td className="text-right">
                    <Gated value={r.offense}>{(v) => formatNumber(v)}</Gated>
                  </Td>
                  <Td className="text-right">
                    <Gated value={r.defense}>{(v) => formatNumber(v)}</Gated>
                  </Td>
                  <Td className="text-right">
                    <Gated value={r.pace}>{(v) => formatNumber(v)}</Gated>
                  </Td>
                  <Td className="text-right">
                    <Gated value={r.scheduleStrength}>{(v) => formatEdge(v)}</Gated>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
