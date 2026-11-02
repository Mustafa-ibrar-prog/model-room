import { formatSigned } from "@/lib/format";
import { getInjuries } from "@/server/data";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";
import { Gated, Missing, Panel, SourceStamp, Td, Th, Unavailable } from "@/components/ui/primitives";

const STATUS_STYLE: Record<string, string> = {
  out: "bg-danger/15 text-danger",
  doubtful: "bg-edge/15 text-edge",
  questionable: "bg-edge/10 text-edge/90",
};

/** Injury report for one league, from the engine's board. */
export async function InjuryBoard({ league, limit }: { league: League; limit?: number }) {
  const viewer = await getViewer();
  const res = await getInjuries(league, viewer.tier);
  if (!res.ok) return <Unavailable title={`${league.toUpperCase()} injuries unavailable`} body={res.reason} />;
  if (!res.connected) {
    return <Unavailable title={`${league.toUpperCase()} injury feed not connected`} body={res.note ?? "No injury source is connected for this league."} />;
  }
  const rows = limit ? res.rows.slice(0, limit) : res.rows;
  if (!rows.length) return <Unavailable title="No injury designations" body="The latest report lists no players with a game designation." />;

  return (
    <Panel>
      <div className="flex flex-wrap items-center gap-2 border-b border-navy-700 px-4 py-3">
        <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} injury report</h3>
        {res.note && <SourceStamp>{res.note}</SourceStamp>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] border-collapse text-[0.95rem]">
          <caption className="sr-only">{league.toUpperCase()} players with a game designation and the model&rsquo;s adjustment, where one applies.</caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="sticky left-0 z-10 bg-navy-850">Player</Th>
              <Th>Team</Th>
              <Th>Status</Th>
              <Th>Injury</Th>
              <Th>Practice</Th>
              <Th className="text-right">Spread impact</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.team}-${r.player}-${i}`} className="border-t border-navy-700/70">
                <Td className="sticky left-0 z-10 bg-navy-900">
                  <span className="font-600 text-ink">{r.player}</span>
                  {r.position && <span className="ml-2 text-sm text-faint">{r.position}</span>}
                </Td>
                <Td className="font-display font-600 text-mute">{r.team}</Td>
                <Td>
                  {r.status ? (
                    <span className={`rounded-md px-2 py-0.5 text-sm font-600 ${STATUS_STYLE[r.status.toLowerCase()] ?? "bg-navy-800 text-mute"}`}>{r.status}</span>
                  ) : (
                    <Missing />
                  )}
                </Td>
                <Td className="text-mute">{r.injury ?? <Missing />}</Td>
                <Td className="text-mute">{r.practice ?? <Missing />}</Td>
                <Td className="text-right font-display font-600">
                  <Gated value={r.impactPoints}>
                    {(v) => (v == null ? <span className="text-sm font-400 text-faint" title={r.impactNote ?? undefined}>Not modeled</span> : <span className="text-edge">{formatSigned(v)} pts</span>)}
                  </Gated>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
