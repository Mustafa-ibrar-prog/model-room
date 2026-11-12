/**
 * The player analysis panel's collapsible sections. Each is a native <details>: closed by default, opened only by
 * the reader, keyboard accessible without script. Every figure here is read from the published board or the injury
 * feed; nothing is recalculated, and nothing here feeds the model.
 */
import type { ReactNode } from "react";
import { sourceLabel } from "@/components/injuries/InjuryFlags";
import { LockedCell } from "@/components/ui/primitives";
import { formatTimestamp } from "@/lib/format";
import type { ContributionView, ExplorerRow, HistoryView } from "@/server/data/explorer";
import { isLocked, type League } from "@/types/domain";

export function Section({ title, summary, children, warn = false }: { title: string; summary: ReactNode; children: ReactNode; warn?: boolean }) {
  return (
    <details className="group border-t border-navy-700">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 py-2.5 text-sm [&::-webkit-details-marker]:hidden">
        <span className="font-500 text-ink">{title}</span>
        <span className={`ml-auto truncate text-right text-xs ${warn ? "text-edge" : "text-faint"}`}>{summary}</span>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          className="shrink-0 text-faint transition-transform group-open:rotate-180 motion-reduce:transition-none">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </summary>
      <div className="space-y-3 pb-4 text-xs text-mute">{children}</div>
    </details>
  );
}

const pctOff = (f: number) => `${Math.abs((f - 1) * 100).toFixed(0)}%`;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const f1 = (n: number) => (Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1));

// ------------------------------------------------------------------ injuries
type InjRow = { player: string; position: string | null; status: string; source: string; reportTime: string | null };
export type InjuryFeed = { team: string; rows: InjRow[] }[] | null;

const ORDER: Record<string, number> = { out: 0, doubtful: 1, questionable: 2 };

/** "3 out · 2 questionable" across both teams (feed rows), or why there is no count. */
export function injurySummary(feed: InjuryFeed, modelAbsences: string | null): string {
  if (!feed) return modelAbsences ? `${modelAbsences.split(", ").length} counted out by the model` : "No injury feed";
  const all = feed.flatMap((t) => t.rows);
  const n = (s: string) => all.filter((r) => r.status === s).length;
  const parts = [[n("out"), "out"], [n("doubtful"), "doubtful"], [n("questionable"), "questionable"]].filter(([c]) => (c as number) > 0).map(([c, l]) => `${c} ${l}`);
  return parts.length ? parts.join(" · ") : "None reported";
}

function handling(league: League, own: boolean, r: InjRow, modelOut: Set<string>, recorded: Set<string>): { text: string; recorded: boolean } {
  if (!own) return { text: league === "nba" ? "Not used: the opponent's defense is a season figure." : "Not used by the model.", recorded: false };
  if (league === "nba") {
    if (modelOut.has(r.player)) return { text: "Counted out by the model (missed his team's last 2 games); his minutes and shots go to teammates.", recorded: true };
    if (r.status === "questionable") return { text: "Projected as playing (the model does not read the injury report).", recorded: false };
    return { text: "Not counted out by the model: it counts a rotation player out only once he has missed his team's last 2 games.", recorded: false };
  }
  if (recorded.has(r.player)) return { text: "Removed from the projection; his share goes to teammates.", recorded: true };
  if (r.status === "questionable") return { text: "Projected as playing.", recorded: false };
  return { text: "Out or Doubtful players are removed from projections; no change recorded on this player's projection.", recorded: false };
}

export function InjurySection({ league, r, feed, feedAt }: { league: League; r: ExplorerRow; feed: InjuryFeed; feedAt: string | null }) {
  const modelOut = new Set((r.modelAbsences ?? "").split(", ").filter(Boolean));
  const recorded = new Set(r.teammatesOut.map((t) => t.name));
  const i = r.injury;
  const teams = [{ abbr: r.team, own: true }, { abbr: r.opp, own: false }];
  const listed = new Set((feed ?? []).flatMap((t) => t.rows.map((x) => x.player)));
  const modelOnly = [...modelOut].filter((n) => !listed.has(n));
  return (
    <Section title="Injuries & availability" summary={injurySummary(feed, r.modelAbsences)}>
      <p className="rounded-md bg-navy-850 px-3 py-2 leading-relaxed">
        {league === "nba"
          ? <><span className="text-ink">How the active NBA model handles absences:</span> it does not read the injury report. A rotation player who missed his team&apos;s last 2 games counts as out, and his minutes and shots go to available teammates. Everyone else is projected as playing.</>
          : <><span className="text-ink">How the active NFL model handles absences:</span> Out and Doubtful players are removed and their share goes to teammates; Questionable players are projected as playing. The opponent&apos;s injuries are not used.</>}
      </p>

      <div>
        <h4 className="text-[0.68rem] text-faint">{r.name}</h4>
        {i?.status ? (
          <p>
            <span className={i.status === "available" ? "text-good" : "text-edge"}>{i.lateScratch ? "Late scratch: " : ""}{i.rawStatus ?? i.status}</span>
            {" "}· {i.confirmed ? "official report" : "reported, not yet official"} · {sourceLabel(i.source)}{i.reportTime ? `, ${formatTimestamp(i.reportTime)}` : ""}
            {i.starterConfirmed != null ? ` · ${i.starterConfirmed ? "confirmed starter" : "not in the confirmed starting five"}` : ""}
          </p>
        ) : r.injuryStatus ? <p className="text-edge">{r.injuryStatus}</p> : <p>Not on the injury report.</p>}
        {i?.conflict ? <p className="text-edge">Sources disagree: {i.conflict}. The official designation is used.</p> : null}
        {i?.startingQb ? <p>Projected starting QB: <span className="text-ink">{i.startingQb}</span></p> : null}
        {i?.notes.map((n) => <p key={n}>{n}</p>)}
        {r.changes ? (
          <p className="text-edge">
            Updated for injury news{r.changes.previous_at ? ` since ${formatTimestamp(r.changes.previous_at)}` : ""}: {r.changes.reasons.join("; ")}.{" "}
            <span className="text-mute">{r.changes.markets.map((m) => `${m.label} ${m.from} → ${m.to}`).join(", ")}</span>
          </p>
        ) : null}
      </div>

      {teams.map((t) => {
        const rows = feed?.find((x) => x.team === t.abbr)?.rows ?? null;
        return (
          <div key={t.abbr}>
            <h4 className="mb-1 text-[0.68rem] text-faint">{t.own ? `His team (${t.abbr})` : `Opponent (${t.abbr})`}</h4>
            {rows === null ? <p>No injury feed this refresh.</p> : !rows.length ? <p>Nobody listed Out, Doubtful or Questionable.</p> : (
              <ul className="divide-y divide-navy-700/70">
                {[...rows].sort((a, b) => (ORDER[a.status] ?? 3) - (ORDER[b.status] ?? 3)).map((x) => {
                  const h = handling(league, t.own, x, modelOut, recorded);
                  const sure = x.status === "out";
                  return (
                    <li key={`${x.player}-${x.status}`} className="py-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-ink">{x.player}</span>
                        {x.position ? <span className="text-faint">{x.position}</span> : null}
                        <span className={`ml-auto rounded-full px-2 py-px text-[0.68rem] ${sure ? "bg-navy-700 text-ink" : "border border-pending/70 text-pending"}`}>
                          {x.status[0].toUpperCase() + x.status.slice(1)}{sure ? "" : " · uncertain"}
                        </span>
                      </div>
                      <p className="text-[0.7rem] text-faint">{h.text} {h.recorded ? <span className="text-mute">Adjustment recorded.</span> : t.own ? "No adjustment recorded." : null}</p>
                    </li>
                  );
                })}
              </ul>
            )}
            {t.own && league === "nba" && modelOnly.length ? <p className="mt-1">Also counted out by the model (not on the report): <span className="text-ink">{modelOnly.join(", ")}</span>.</p> : null}
            {t.own && league === "nfl" && r.teammatesOut.filter((x) => !listed.has(x.name)).length ? (
              <p className="mt-1">Also removed from the projection: <span className="text-ink">{r.teammatesOut.filter((x) => !listed.has(x.name)).map((x) => x.name).join(", ")}</span>.</p>
            ) : null}
          </div>
        );
      })}
      <p className="text-[0.68rem] text-faint">
        Out = listed Out on the report. Doubtful and Questionable players may or may not play (shown in amber). Injury feed {feedAt ? `updated ${formatTimestamp(feedAt)}` : "not available this refresh"}.
      </p>
    </Section>
  );
}

// ------------------------------------------------------------------ minutes & opportunity
function avgOpp(h: HistoryView, key: string, n: number): number | null {
  const v = h.games.slice(0, n).map((g) => g.opp_[key]).filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

export function OpportunitySection({ league, r, contributions }: { league: League; r: ExplorerRow; contributions: ContributionView | null }) {
  const h = r.history;
  const inp = isLocked(r.inputs) ? null : r.inputs;
  const main = h.opportunity[0];
  const last5 = main ? avgOpp(h, main.key, 5) : null;
  const seasonV = main ? h.season?.opportunity[main.key] ?? null : null;
  const projMin = league === "nba" ? num(inp?.projected_minutes) ?? contributions?.minutes?.projected ?? null : null;
  const usualMin = contributions?.minutes?.usual ?? null;
  const summary = projMin != null ? `${projMin.toFixed(1)} projected min` : last5 != null && main ? (main.key === "snap_pct" ? `${Math.round(last5)}% of snaps, last 5` : `${f1(last5)} ${main.label.toLowerCase()}, last 5`) : "No recent games";
  const roleShift = last5 != null && seasonV != null && h.season && h.season.games >= 3
    ? (league === "nba" ? Math.abs(last5 - seasonV) >= 4 : main?.key === "snap_pct" ? Math.abs(last5 - seasonV) >= 10 : false)
    : false;
  const rows: [string, string][] = [];
  if (league === "nba") {
    if (projMin != null) rows.push(["Projected minutes", `${projMin.toFixed(1)}${usualMin != null ? ` (usual ${usualMin.toFixed(1)})` : ""}`]);
    const sr = num(inp?.starter_rate);
    if (sr != null) rows.push(["Started", `${Math.round(sr * 10)} of his last 10`]);
    const ar = num(inp?.appear_rate_last10);
    if (ar != null) rows.push(["Played", `${Math.round(ar * 10)} of his team's last 10`]);
    const uf = num(inp?.usage_freed_by_absences);
    if (uf != null) rows.push(["Extra usage from teammates out", `${(uf * 100).toFixed(1)}%`]);
  } else {
    const ss = num(inp?.snap_share_recent);
    if (ss != null) rows.push(["Recent snap share (model input)", `${(ss * 100).toFixed(0)}%`]);
    const ts = num(inp?.target_share);
    if (ts != null && ts > 0) rows.push(["Target share", `${(ts * 100).toFixed(1)}%`]);
    const cs = num(inp?.carry_share);
    if (cs != null && cs > 0) rows.push(["Carry share", `${(cs * 100).toFixed(1)}%`]);
    const tp = num(inp?.team_pass_attempts);
    if (tp != null) rows.push(["Team pass attempts (projected)", f1(tp)]);
    const tc = num(inp?.team_carries);
    if (tc != null) rows.push(["Team carries (projected)", f1(tc)]);
  }
  return (
    <Section title="Minutes & opportunity" summary={summary}>
      {h.opportunity.length && h.games.length ? (
        <div>
          <h4 className="mb-1 text-[0.68rem] text-faint">Opportunity per game (not results)</h4>
          <table className="w-full">
            <thead className="text-faint"><tr><th className="py-0.5 text-left font-400" /><th className="text-right font-400">Last 5</th><th className="text-right font-400">Last 10</th><th className="text-right font-400">Season</th></tr></thead>
            <tbody>
              {h.opportunity.map((o) => {
                const a5 = avgOpp(h, o.key, 5);
                const a10 = h.games.length > 5 ? avgOpp(h, o.key, 10) : null;
                const s = h.season?.opportunity[o.key];
                return (
                  <tr key={o.key} className="border-t border-navy-700/70">
                    <td className="py-1 text-mute">{o.label}</td>
                    <td className="text-right font-mono text-ink">{a5 != null ? f1(a5) : "–"}</td>
                    <td className="text-right font-mono text-ink">{a10 != null ? f1(a10) : "–"}</td>
                    <td className="text-right font-mono text-ink">{s != null ? f1(s) : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-1 text-[0.68rem] text-faint">
            Games: last 5 = {Math.min(5, h.games.length)}, last 10 = {h.games.length > 5 ? Math.min(10, h.games.length) : "not published"}, season = {h.season ? `${h.season.games} regular-season` : "not published"}.
          </p>
        </div>
      ) : <p>No recent opportunity data on this board.</p>}
      {roleShift && main ? (
        <p className="text-ink">Role change: {main.label.toLowerCase()} over his last 5 ({f1(last5!)}) differ from his season average ({f1(seasonV!)}).</p>
      ) : null}
      {inp ? (
        rows.length ? (
          <dl className="space-y-0.5">
            {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt>{k}</dt><dd className="font-mono text-ink">{v}</dd></div>)}
          </dl>
        ) : null
      ) : (
        <div className="flex items-center gap-2 text-faint"><span>Projected minutes, usage and shares are model inputs, part of Pro.</span><LockedCell requires={(r.inputs as { requires: Parameters<typeof LockedCell>[0]["requires"] }).requires} /></div>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------ matchup
const NBA_OPP: Record<string, string> = { points: "opp_points_factor", rebounds: "opp_rebounds_factor", assists: "opp_assists_factor", pra: "opp_points_factor", threes: "opp_points_factor" };

export function MatchupSection({ league, r, cat, contributions }: { league: League; r: ExplorerRow; cat: string; contributions: ContributionView | null }) {
  const inp = isLocked(r.inputs) ? null : r.inputs;
  const lines: string[] = [];
  let summary = "Part of Pro";
  let lean: number | null = null;
  if (inp && league === "nba") {
    const k = NBA_OPP[cat];
    const f = k ? num(inp[k]) : null;
    if (f != null) {
      lean = f;
      const what = k.replace("opp_", "").replace("_factor", "");
      lines.push(`${r.opp}'s defense against his position: ${Math.abs(f - 1) < 0.005 ? "league average" : `${pctOff(f)} ${f > 1 ? "more" : "fewer"} ${what} than average`}${cat === "pra" || cat === "threes" ? " (scoring factor)" : ""}.`);
    }
    for (const kk of ["opp_points_factor", "opp_rebounds_factor", "opp_assists_factor"]) {
      const v = num(inp[kk]);
      if (v != null && kk !== k) lines.push(`Opponent ${kk.replace("opp_", "").replace("_factor", "")} factor: ${v.toFixed(3)}.`);
    }
    const pf = num(inp.pace_factor);
    if (pf != null) lines.push(`Projected pace: ${Math.abs(pf - 1) < 0.005 ? "about his team's usual" : `${pctOff(pf)} ${pf > 1 ? "faster" : "slower"} than his team's usual`}.`);
  } else if (inp) {
    const yf = num(inp.yards_factor);
    if (yf != null) { lean = yf; lines.push(`${r.opp}'s efficiency allowed (yards): ${Math.abs(yf - 1) < 0.005 ? "league average" : `${pctOff(yf)} ${yf > 1 ? "above" : "below"} average`}.`); }
    const cv = num(inp.coverage_factor);
    if (cv != null) lines.push(`Coverage factor: ${cv.toFixed(3)}${Math.abs(cv - 1) < 0.005 ? " (neutral)" : ""}.`);
    const bf = num(inp.blitz_factor);
    if (bf != null) lines.push(`Blitz factor: ${bf.toFixed(3)}${Math.abs(bf - 1) < 0.005 ? " (neutral)" : ""}.`);
    const cr = num(inp.catch_rate);
    if (cr != null) lines.push(`His catch rate (model input): ${(cr * 100).toFixed(0)}%.`);
    const tp = num(inp.team_pass_attempts);
    const tc = num(inp.team_carries);
    if (tp != null || tc != null) lines.push(`Game environment: ${tp != null ? `${f1(tp)} team pass attempts` : ""}${tp != null && tc != null ? ", " : ""}${tc != null ? `${f1(tc)} team carries` : ""} projected.`);
  }
  if (inp) summary = lean == null ? "See details" : Math.abs(lean - 1) < 0.03 ? "opponent about average" : lean > 1 ? "softer opponent" : "tougher opponent";
  const step = contributions?.steps?.find((s) => s.key === "matchup" || s.key === "matchup_efficiency");
  return (
    <Section title="Matchup" summary={summary}>
      {inp ? (
        <>
          {lines.length ? <ul className="space-y-1">{lines.map((l) => <li key={l}>{l}</li>)}</ul> : <p>No matchup factors recorded for this projection.</p>}
          {step ? <p>Effect on his average (recorded): <span className="font-mono text-ink">{step.value >= 0 ? "+" : "−"}{Math.abs(step.value).toFixed(1)}</span>.</p> : null}
        </>
      ) : (
        <div className="flex items-center gap-2 text-faint"><span>Opponent and pace factors are model inputs, part of Pro.</span><LockedCell requires={(r.inputs as { requires: Parameters<typeof LockedCell>[0]["requires"] }).requires} /></div>
      )}
      <p className="text-faint">Individual defender matchups are not modelled; the opponent factor covers his position as a whole.</p>
    </Section>
  );
}

// ------------------------------------------------------------------ data & model
export function DataSection({ league, version, generatedAt, feedAt, lineSeen, lineStale, now, support, supportNote, history, seasonText }: {
  league: League; version: string; generatedAt: string; feedAt: string | null; lineSeen: string | null; lineStale: boolean; now: number;
  support: string; supportNote: string; history: HistoryView; seasonText: string;
}) {
  const runAge = (now - Date.parse(generatedAt)) / 3.6e6;
  const staleRun = runAge > 18;
  const summary = lineStale ? "line may have moved" : staleRun ? "model run is old" : `run ${formatTimestamp(generatedAt).replace(/^\w+ \d+, /, "")}`;
  return (
    <Section title="Data & model" summary={summary} warn={lineStale || staleRun}>
      <dl className="space-y-1">
        <div className="flex justify-between gap-3"><dt>Active model</dt><dd className="text-ink">{league.toUpperCase()} props {version}</dd></div>
        <div className="flex justify-between gap-3"><dt>Model run</dt><dd className={staleRun ? "text-edge" : "text-ink"}>{formatTimestamp(generatedAt)}{staleRun ? ` · ${Math.round(runAge)} h ago` : ""}</dd></div>
        <div className="flex justify-between gap-3"><dt>Injury feed</dt><dd className="text-ink">{feedAt ? formatTimestamp(feedAt) : "not available"}</dd></div>
        <div className="flex justify-between gap-3"><dt>Market line seen</dt><dd className={lineStale ? "text-edge" : "text-ink"}>{lineSeen ? formatTimestamp(lineSeen) : "no market line"}{lineStale ? " · may have moved" : ""}</dd></div>
        <div className="flex justify-between gap-3"><dt>Player history</dt><dd className="text-right text-ink">{support}</dd></div>
        <div className="flex justify-between gap-3"><dt>Past games published</dt><dd className="text-right text-ink">{history.games.length}{history.season ? ` · ${history.season.games} in ${seasonText}` : ""}</dd></div>
      </dl>
      <p>{supportNote}</p>
      <p className="text-faint">The model never sees market prices; market lines are shown beside it, not fed into it. Past games and season averages are shown for context and are not model inputs.</p>
    </Section>
  );
}
