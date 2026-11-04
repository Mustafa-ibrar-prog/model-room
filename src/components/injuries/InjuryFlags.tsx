import Link from "next/link";
import { formatTimestamp } from "@/lib/format";
import type { League } from "@/types/domain";
import type { EngineAvailability, EngineFlag } from "@/types/engine";

const LABEL: Record<EngineFlag["status"], string> = { out: "Out", doubtful: "Doubtful", questionable: "Questionable", probable: "Probable" };
const TONE: Record<EngineFlag["status"], string> = {
  out: "border-danger/50 text-danger",
  doubtful: "border-danger/40 text-danger/90",
  questionable: "border-edge/50 text-edge",
  probable: "border-navy-600 text-mute",
};
const SOURCE: Record<string, string> = { nba_official: "NBA official report", espn: "ESPN report", nflverse: "NFL injury report (nflverse)" };

export const sourceLabel = (s: string | null | undefined) => (s ? (SOURCE[s] ?? s) : "unknown source");

/** "Confirmed" only for the league's own designation; everything else is a report. */
export function Confirmed({ confirmed }: { confirmed: boolean }) {
  return confirmed ? <span className="text-good">confirmed</span> : <span className="text-faint">reported</span>;
}

function Chip({ f }: { f: EngineFlag }) {
  const title = [
    `${f.player}${f.position ? ` (${f.position})` : ""}: ${f.raw_status ?? LABEL[f.status]}`,
    f.detail,
    `${sourceLabel(f.source)}${f.report_time ? `, ${formatTimestamp(f.report_time)}` : ""}`,
    f.confirmed ? "Official designation" : "Report, not an official designation",
    f.conflict ? `Sources disagree: ${f.conflict}` : null,
    f.late_scratch ? "Late scratch" : null,
  ].filter(Boolean).join(" · ");
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] ${TONE[f.status]}`}>
      <span className="font-600">{f.late_scratch ? "Late scratch" : LABEL[f.status]}</span>
      <span className="text-ink">{f.player}</span>
      {f.position ? <span className="text-faint">{f.position}</span> : null}
      {f.conflict ? <span aria-label="sources disagree" className="text-edge">≠</span> : null}
    </span>
  );
}

/** Rank who matters: QBs and ruled-out players first; long-term absences (already in the ratings) last. */
function order(f: EngineFlag): number {
  const s = { out: 0, doubtful: 1, questionable: 2, probable: 3 }[f.status];
  return (f.long_term ? 10 : 0) + (f.position === "QB" ? -1 : 0) + s;
}

/** One line per game: what changed (if the projection moved because of it) and the designated players. */
export function InjuryLine({ a, changes, league, home, away, quarterbacks, max = 6 }: {
  a: EngineAvailability | null;
  changes?: { reasons: string[]; moved: Record<string, { from: number; to: number }>; previous_at: string | null } | null;
  league: League;
  home: string;
  away: string;
  quarterbacks?: { home: string | null; away: string | null } | null;
  max?: number;
}) {
  if (!a) return null;
  const flags = [...a.away.map((f) => ({ f, t: away })), ...a.home.map((f) => ({ f, t: home }))]
    .filter(({ f }) => f.status !== "probable")
    .sort((x, y) => order(x.f) - order(y.f));
  if (!flags.length && !changes) return null;
  const shown = flags.slice(0, max);
  const label = (k: string) => (k === "home_win_prob" ? "win %" : k);
  return (
    <div className="col-span-full space-y-1 border-t border-navy-700/50 pt-2 text-xs">
      {changes ? (
        <p className="text-edge">
          <span className="font-600">Updated for injuries:</span> {changes.reasons.join("; ")}
          {Object.keys(changes.moved).length ? (
            <span className="text-mute">
              {" "}({Object.entries(changes.moved).map(([k, v]) => `${label(k)} ${k === "home_win_prob" ? `${Math.round(v.from * 100)}→${Math.round(v.to * 100)}%` : `${v.from}→${v.to}`}`).join(", ")}
              {changes.previous_at ? ` since ${formatTimestamp(changes.previous_at)}` : ""})
            </span>
          ) : null}
        </p>
      ) : null}
      {league === "nfl" && quarterbacks && (quarterbacks.home || quarterbacks.away) ? (
        <p className="text-faint">Projected QBs: {away} {quarterbacks.away ?? "unknown"}, {home} {quarterbacks.home ?? "unknown"}</p>
      ) : null}
      {shown.length ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {shown.map(({ f, t }) => (
            <span key={`${t}-${f.player_id}`} className="inline-flex items-center gap-1"><span className="font-mono text-[0.62rem] text-faint">{t}</span><Chip f={f} /></span>
          ))}
          {flags.length > shown.length ? (
            <Link href={`/injuries?sport=${league}`} className="text-[0.7rem] text-model hover:underline">+{flags.length - shown.length} more</Link>
          ) : null}
        </div>
      ) : null}
      <p className="text-[0.65rem] text-faint">
        Injury info {a.updated_at ? `as of ${formatTimestamp(a.updated_at)}` : ""} from {a.sources.map(sourceLabel).join(" + ") || "no source"}. Official designations are marked confirmed; ESPN entries are reports.
      </p>
    </div>
  );
}
