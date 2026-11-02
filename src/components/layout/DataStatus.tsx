import { formatDateShort, formatTimestamp } from "@/lib/format";
import { getFreshness } from "@/server/data";
import type { Freshness, League } from "@/types/domain";

const STYLE: Record<Freshness["status"], string> = {
  current: "bg-model text-navy-950",
  delayed: "bg-edge text-navy-950",
  unavailable: "bg-navy-600 text-ink",
};
const LABEL: Record<Freshness["status"], string> = { current: "Current", delayed: "Delayed", unavailable: "Unavailable" };

/** Per-league data status under the header. Never says "live". */
export async function DataStatus() {
  const [nba, nfl] = await Promise.all([getFreshness("nba"), getFreshness("nfl")]);
  return (
    <div role="status" className="border-b border-navy-700/70 bg-navy-900/70">
      <div className="mx-auto flex max-w-7xl flex-wrap gap-x-6 gap-y-1.5 px-4 py-2 text-[0.8rem] text-mute sm:px-6">
        <LeagueStatus league="nba" f={nba} />
        <LeagueStatus league="nfl" f={nfl} />
      </div>
    </div>
  );
}

function LeagueStatus({ league, f }: { league: League; f: Freshness }) {
  const through = f.resultsThrough ? formatDateShort(f.resultsThrough) : "n/a";
  return (
    <p className="flex items-center gap-2" title={f.reasons.join("; ") || undefined}>
      <span className="font-display text-[0.85rem] font-700 text-ink">{league.toUpperCase()}</span>
      <span className={`rounded-sm px-1.5 py-px font-display text-[0.75rem] font-700 ${STYLE[f.status]}`}>{LABEL[f.status]}</span>
      {f.status === "unavailable" ? (
        <span>No projections yet</span>
      ) : (
        <span>
          <span className="sm:hidden">to {through}</span>
          <span className="hidden sm:inline">Results through {through}. Model run {formatTimestamp(f.modelRunAt)}</span>
        </span>
      )}
      {f.status === "delayed" && f.reasons[0] && <span className="hidden text-faint lg:inline">({f.reasons[0]})</span>}
    </p>
  );
}

export function DataStatusFallback() {
  return <div className="h-[33px] border-b border-navy-700/70 bg-navy-900/70" aria-hidden="true" />;
}
