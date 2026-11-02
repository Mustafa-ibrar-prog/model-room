import { formatEdge, formatNumber, formatPct } from "@/lib/format";
import { getPropBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";
import { DemoStamp, Gated, LockedPanel, Panel, Td, Th } from "@/components/ui/primitives";

/** Player prop projections. Free viewers receive no prop data at all. */
export async function PropBoard({ league }: { league: League }) {
  const viewer = await getViewer();
  const { data } = await getPropBoard(league, viewer.tier);

  if (!data) {
    return (
      <LockedPanel
        requires="plus"
        title={`${league.toUpperCase()} player props`}
        body="Prop projections compare each player's posted line with the model's projection. They are part of Plus and Pro."
      />
    );
  }

  return (
    <Panel>
      <div className="flex items-center gap-2 border-b border-navy-700 px-4 py-3">
        <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} player props</h3>
        <DemoStamp />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse text-[0.95rem]">
          <caption className="sr-only">{league.toUpperCase()} demo player prop projections.</caption>
          <thead className="bg-navy-850">
            <tr>
              <Th className="sticky left-0 z-10 bg-navy-850">Player</Th>
              <Th>Market</Th>
              <Th className="text-right">Line</Th>
              <Th className="text-right">Projection</Th>
              <Th>Edge</Th>
              <Th className="text-right">Over share</Th>
              <Th className="text-right">Projected range</Th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => {
              const size = Math.abs(p.edge);
              const meaningful = size >= p.line * 0.05;
              return (
                <tr key={p.id} className="border-t border-navy-700/70">
                  <Td className="sticky left-0 z-10 bg-navy-900">
                    <div className="font-600 text-ink">{p.player}</div>
                    <div className="text-[0.8rem] text-faint">
                      {p.team.abbr} vs {p.opponent.abbr}
                    </div>
                  </Td>
                  <Td className="text-mute">{p.market}</Td>
                  <Td className="text-right font-display text-lg font-600 text-market">{formatNumber(p.line)}</Td>
                  <Td className="text-right font-display text-lg font-600 text-model">{formatNumber(p.projection)}</Td>
                  <Td>
                    {meaningful ? (
                      <span className="rounded-md bg-edge/15 px-2 py-0.5 font-display font-600 text-edge">
                        {p.edge > 0 ? "Over" : "Under"} {formatEdge(size).replace("+", "")}
                      </span>
                    ) : (
                      <span className="text-sm text-faint">No edge</span>
                    )}
                  </Td>
                  <Td className="text-right text-ink/90">
                    <Gated value={p.overShare}>{(v) => formatPct(v)}</Gated>
                  </Td>
                  <Td className="text-right text-ink/90">
                    <Gated value={p.range}>{(r) => `${r.low}–${r.high}`}</Gated>
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
