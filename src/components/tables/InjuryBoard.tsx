import Link from "next/link";
import { formatSigned } from "@/lib/format";
import { getInjuries } from "@/server/data";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";
import { AutoSubmit } from "@/components/props/AutoSubmit";
import { Gated, Panel, SourceStamp, Unavailable } from "@/components/ui/primitives";

const STATUS_STYLE: Record<string, string> = {
  out: "bg-danger/15 text-danger",
  doubtful: "bg-edge/15 text-edge",
  questionable: "bg-edge/10 text-edge/90",
};
const ORDER = ["out", "doubtful", "questionable"];

/**
 * Injury report for one league, from the engine's board. With `filters`: status chips and a team picker
 * (URL parameters, so they work without JavaScript and can be shared). Phones get a stacked list; wider
 * screens a table.
 */
export async function InjuryBoard({ league, limit, team, status, filters = false }: { league: League; limit?: number; team?: string; status?: string; filters?: boolean }) {
  const viewer = await getViewer();
  const res = await getInjuries(league, viewer.tier);
  if (!res.ok) return <Unavailable title={`${league.toUpperCase()} injuries unavailable`} body={res.reason} />;
  if (!res.connected) {
    return <Unavailable title={`${league.toUpperCase()} injury feed not connected`} body={res.note ?? "No injury source is connected for this league."} />;
  }
  const all = res.rows;
  const teams = [...new Set(all.map((r) => r.team))].sort();
  const st = status?.toLowerCase();
  let rows = all.filter((r) => (!team || r.team === team) && (!st || (r.status ?? "").toLowerCase() === st));
  if (limit) rows = rows.slice(0, limit);
  const count = (s: string) => all.filter((r) => (!team || r.team === team) && (r.status ?? "").toLowerCase() === s).length;
  const statuses = ORDER.filter((s) => all.some((r) => (r.status ?? "").toLowerCase() === s));
  const href = (patch: Record<string, string | undefined>) => {
    const p = new URLSearchParams({ sport: league });
    const v = { team, status: st, ...patch };
    for (const [k, x] of Object.entries(v)) if (x) p.set(k, x);
    return `/injuries?${p.toString()}`;
  };
  const chip = (on: boolean) => `whitespace-nowrap rounded-full px-3 py-1 text-sm ${on ? "bg-ink font-600 text-navy-950" : "bg-navy-850 text-mute hover:text-ink"}`;

  return (
    <Panel>
      <div className="flex flex-wrap items-center gap-2 border-b border-navy-700 px-4 py-3">
        <h3 className="font-display text-lg font-600 text-ink">{league.toUpperCase()} injury report</h3>
        {res.note && <SourceStamp>{res.note}</SourceStamp>}
      </div>
      {filters ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-navy-700 px-4 py-3">
          <nav aria-label="Status" className="-mx-1 flex gap-1 overflow-x-auto px-1">
            <Link href={href({ status: undefined })} className={chip(!st)}>All {team ? "" : all.length}</Link>
            {statuses.map((s) => (
              <Link key={s} href={href({ status: s })} className={chip(st === s)}>
                {s[0].toUpperCase() + s.slice(1)} <span className={st === s ? "" : "text-faint"}>{count(s)}</span>
              </Link>
            ))}
          </nav>
          <form action="/injuries" className="ml-auto">
            <input type="hidden" name="sport" value={league} />
            {st ? <input type="hidden" name="status" value={st} /> : null}
            <select name="team" aria-label="Team" defaultValue={team ?? ""} className="rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm text-ink">
              <option value="">All teams</option>
              {teams.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <noscript><button type="submit" className="ml-1 text-sm text-mute">Go</button></noscript>
            <AutoSubmit />
          </form>
        </div>
      ) : null}
      {!rows.length ? (
        <p className="px-4 py-8 text-center text-sm text-mute">{all.length ? "No players match these filters." : "The latest report lists no players with a game designation."}</p>
      ) : (
        <>
          {/* Phones: one stacked row per player. */}
          <ul className="divide-y divide-navy-700/70 sm:hidden">
            {rows.map((r, i) => (
              <li key={`${r.team}-${r.player}-${i}`} className="flex items-start gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate">
                    <span className="font-600 text-ink">{r.player}</span>
                    {r.position ? <span className="ml-1.5 text-sm text-faint">{r.position}</span> : null}
                  </div>
                  <div className="truncate text-xs text-mute">
                    <span className="font-display font-600">{r.team}</span>
                    {r.injury ? ` · ${r.injury}` : ""}
                    {r.practice ? ` · ${r.practice}` : ""}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  {r.status ? <span className={`rounded-md px-2 py-0.5 text-xs font-600 ${STATUS_STYLE[r.status.toLowerCase()] ?? "bg-navy-800 text-mute"}`}>{r.status}</span> : null}
                  <div className="mt-1 text-xs">
                    <Gated value={r.impactPoints}>{(v) => (v == null ? null : <span className="font-600 text-edge">{formatSigned(v)} pts</span>)}</Gated>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {/* Wider screens: the table. */}
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full border-collapse text-[0.95rem]">
              <caption className="sr-only">{league.toUpperCase()} players with a game designation and the model&rsquo;s adjustment, where one applies.</caption>
              <thead className="bg-navy-850 text-left text-xs text-faint">
                <tr>
                  <th className="px-4 py-2 font-500">Player</th>
                  <th className="px-3 py-2 font-500">Team</th>
                  <th className="px-3 py-2 font-500">Status</th>
                  <th className="px-3 py-2 font-500">Injury</th>
                  <th className="px-3 py-2 font-500">Practice</th>
                  <th className="px-4 py-2 text-right font-500">Spread impact</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.team}-${r.player}-${i}`} className="border-t border-navy-700/70">
                    <td className="px-4 py-2">
                      <span className="font-600 text-ink">{r.player}</span>
                      {r.position && <span className="ml-2 text-sm text-faint">{r.position}</span>}
                    </td>
                    <td className="px-3 py-2 font-display font-600 text-mute">{r.team}</td>
                    <td className="px-3 py-2">
                      {r.status ? <span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-sm font-600 ${STATUS_STYLE[r.status.toLowerCase()] ?? "bg-navy-800 text-mute"}`}>{r.status}</span> : <span className="text-faint">–</span>}
                    </td>
                    <td className="px-3 py-2 text-mute">{r.injury ?? <span className="text-faint">–</span>}</td>
                    <td className="px-3 py-2 text-mute">{r.practice ?? <span className="text-faint">–</span>}</td>
                    <td className="px-4 py-2 text-right font-display font-600">
                      <Gated value={r.impactPoints}>
                        {(v) => (v == null ? <span className="text-sm font-400 text-faint" title={r.impactNote ?? undefined}>Not modeled</span> : <span className="text-edge">{formatSigned(v)} pts</span>)}
                      </Gated>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {limit && all.length > rows.length ? (
            <div className="border-t border-navy-700 px-4 py-2.5 text-right">
              <Link href={`/injuries?sport=${league}`} className="text-sm font-600 text-model hover:underline">All {all.length} {league.toUpperCase()} designations</Link>
            </div>
          ) : null}
        </>
      )}
    </Panel>
  );
}
