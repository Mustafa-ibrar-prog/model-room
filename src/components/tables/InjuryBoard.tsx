import { formatEdge } from "@/lib/format";
import { getInjuryReport } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type InjuryReport, type InjuryStatus, type League } from "@/types/domain";
import { DemoStamp, Gated, LockedCell, Panel, Td, Th } from "@/components/ui/primitives";

const STATUS_STYLE: Record<InjuryStatus, string> = {
  Out: "bg-danger/15 text-danger",
  Doubtful: "bg-edge/15 text-edge",
  Questionable: "bg-edge/10 text-edge/90",
  "Day-to-day": "bg-market/15 text-market",
  Probable: "bg-model/10 text-model",
};

/** Injury impact dashboard for one league. Render inside <Suspense>. */
export async function InjuryBoard({ league, compact = false }: { league: League; compact?: boolean }) {
  const viewer = await getViewer();
  const { data } = await getInjuryReport(league, viewer.tier);
  const rows = compact ? data.slice(0, 4) : data;
  const impactLocked = data.length > 0 && isLocked(data[0].spreadImpact);

  return (
    <div className="space-y-4">
      {!compact && <InjurySummary rows={data} impactLocked={impactLocked} />}
      <Panel>
        <div className="flex items-center gap-2 border-b border-navy-700 px-4 py-3">
          <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} injury report</h3>
          <DemoStamp />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-[0.95rem]">
            <caption className="sr-only">{league.toUpperCase()} demo injury report with projected line impact.</caption>
            <thead className="bg-navy-850">
              <tr>
                <Th className="sticky left-0 z-10 bg-navy-850">Player</Th>
                <Th>Team</Th>
                <Th>Status</Th>
                <Th>Detail</Th>
                <Th className="text-right">Spread impact</Th>
                <Th className="text-right">Total impact</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-navy-700/70">
                  <Td className="sticky left-0 z-10 bg-navy-900">
                    <span className="font-600 text-ink">{r.player}</span>
                    <span className="ml-2 text-sm text-faint">{r.position}</span>
                  </Td>
                  <Td className="font-display font-600 text-mute">{r.team.abbr}</Td>
                  <Td>
                    <span className={`rounded-md px-2 py-0.5 text-sm font-600 ${STATUS_STYLE[r.status]}`}>{r.status}</span>
                  </Td>
                  <Td className="text-mute">{r.detail}</Td>
                  <Td className="text-right font-display text-lg font-600">
                    <Gated value={r.spreadImpact}>{(v) => <Impact v={v} unit="pts" />}</Gated>
                  </Td>
                  <Td className="text-right font-display text-lg font-600">
                    <Gated value={r.totalImpact}>{(v) => <Impact v={v} unit="pts" signed />}</Gated>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function Impact({ v, unit, signed = false }: { v: number; unit: string; signed?: boolean }) {
  if (v === 0) return <span className="text-faint">None</span>;
  return (
    <span className={Math.abs(v) >= 1.5 ? "text-edge" : "text-ink/90"}>
      {signed ? formatEdge(v) : v.toFixed(1)} <span className="text-sm font-500 text-faint">{unit}</span>
    </span>
  );
}

function InjurySummary({ rows, impactLocked }: { rows: InjuryReport[]; impactLocked: boolean }) {
  const count = (s: InjuryStatus[]) => rows.filter((r) => s.includes(r.status)).length;
  const biggest = impactLocked
    ? null
    : [...rows].sort((a, b) => Math.abs(b.spreadImpact as number) - Math.abs(a.spreadImpact as number))[0];

  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-navy-700 bg-navy-700 lg:grid-cols-4">
      <Stat label="Ruled out" value={String(count(["Out"]))} tone="text-danger" />
      <Stat label="Doubtful or questionable" value={String(count(["Doubtful", "Questionable", "Day-to-day"]))} tone="text-edge" />
      <Stat label="Probable" value={String(count(["Probable"]))} tone="text-model" />
      <div className="bg-navy-900 px-4 py-4">
        <dt className="text-sm text-mute">Largest line impact</dt>
        <dd className="mt-1">
          {biggest ? (
            <span className="font-display text-2xl font-700 text-edge">
              {biggest.player}
              <span className="ml-2 text-base font-600 text-mute">{(biggest.spreadImpact as number).toFixed(1)} pts</span>
            </span>
          ) : (
            <LockedCell requires="plus" />
          )}
        </dd>
      </div>
    </dl>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="bg-navy-900 px-4 py-4">
      <dt className="text-sm text-mute">{label}</dt>
      <dd className={`mt-1 font-display text-3xl font-700 ${tone}`}>{value}</dd>
    </div>
  );
}
