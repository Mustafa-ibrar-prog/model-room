import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { addDays, etDate, isDate, longDate } from "@/lib/dates";
import { formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { getHistoryDay, type HistoryView } from "@/server/data/history";
import { getViewer } from "@/server/viewer";
import { loadRefreshStatus } from "@/server/engine/board";
import { isLocked, type League } from "@/types/domain";
import type { HistoryPick, HistoryProp } from "@/types/history";
import { LockedPanel, PageHeader, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import { TeamBadge } from "@/components/ui/TeamBadge";

export const metadata: Metadata = { title: "Yesterday's results" };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default function YesterdayPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader
        title="Yesterday"
        intro="What the model said before each game, and what happened. Every number is the last projection recorded before the game started; nothing is recomputed afterwards."
      />
      <Suspense fallback={<div className="mx-auto max-w-7xl px-4 sm:px-6"><TableSkeleton rows={8} /></div>}>
        <Body searchParams={searchParams} />
      </Suspense>
    </>
  );
}

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

async function Body({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const today = etDate();
  const asked = one(sp.date);
  const date = isDate(asked) && asked < today ? asked : addDays(today, -1);
  const viewer = await getViewer();
  const [nfl, nba, refresh] = await Promise.all([getHistoryDay("nfl", date, viewer.tier), getHistoryDay("nba", date, viewer.tier), loadRefreshStatus()]);
  const days = [
    { league: "nba" as League, h: nba },
    { league: "nfl" as League, h: nfl },
  ].filter((d) => d.h.available && d.h.games.length);
  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 pb-16 sm:px-6">
      <nav className="flex items-center justify-between gap-3 text-sm" aria-label="Date">
        <Link href={`/yesterday?date=${addDays(date, -1)}`} className="rounded-md border border-navy-700 px-3 py-1.5 text-mute hover:text-ink">Earlier day</Link>
        <span className="text-center font-600 text-ink">{longDate(date)}</span>
        {addDays(date, 1) < today ? (
          <Link href={`/yesterday?date=${addDays(date, 1)}`} className="rounded-md border border-navy-700 px-3 py-1.5 text-mute hover:text-ink">Next day</Link>
        ) : <span className="w-[5.5rem]" />}
      </nav>
      {!days.length ? <Unavailable title={`No games on ${longDate(date)}`} body="Neither league played that day. Use Earlier day to go back." /> : null}
      {days.map(({ league, h }) => <LeagueDay key={league} league={league} h={h} date={date} />)}
      <p className="text-xs text-faint">
        {refresh?.last_success ? `Last successful data refresh ${formatTimestamp(refresh.last_success.at)} (${refresh.last_success.slot.split(":")[0]}).` : "No logged refresh yet."}
        {refresh?.recent_failures?.length ? ` Last failed refresh ${formatTimestamp(refresh.recent_failures[refresh.recent_failures.length - 1].at)}; the site kept the previous data.` : ""}
        {" "}Refresh schedule: {refresh?.schedule ?? "7:00 AM PT, 12:00 PM PT, and before each game"}. Headline grades use the last projection recorded before each game started; earlier snapshots are kept in the ledger.
      </p>
    </div>
  );
}

type Rec = { w: number; l: number; p: number; pending: number };
const tally = (picks: (HistoryPick | null | undefined)[]): Rec =>
  picks.reduce<Rec>((r, x) => {
    if (!x) return r;
    if (x.result === "win") r.w++;
    else if (x.result === "loss") r.l++;
    else if (x.result === "push") r.p++;
    else r.pending++;
    return r;
  }, { w: 0, l: 0, p: 0, pending: 0 });
const recText = (r: Rec) => (r.w + r.l + r.p ? `${r.w}–${r.l}${r.p ? `–${r.p}` : ""}` : "–");

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-navy-700 bg-navy-900 px-3 py-2.5">
      <div className="text-xs text-faint">{label}</div>
      <div className="font-display text-xl font-700 text-ink">{value}</div>
      {note ? <div className="text-xs text-faint">{note}</div> : null}
    </div>
  );
}

function LeagueDay({ league, h, date }: { league: League; h: HistoryView; date: string }) {
  const lockedGate = h.games.map((g) => g.pregame).find((x) => x != null && isLocked(x));
  const locked = lockedGate != null && isLocked(lockedGate);
  const graded = h.games.filter((g) => g.final && g.pregame && !isLocked(g.pregame) && g.result && !isLocked(g.result));
  const res = graded.map((g) => (g.result && !isLocked(g.result) ? g.result : null)).filter((r): r is NonNullable<typeof r> => r != null);
  const mk = h.games.map((g) => (g.market && !isLocked(g.market) ? g.market : null));
  const spread = tally(mk.map((m) => m?.spread));
  const total = tally(mk.map((m) => m?.total));
  const winners = res.filter((r) => r.winner_correct != null);
  const mae = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + Math.abs(b), 0) / xs.length : null);
  const marginMae = mae(res.map((r) => r.margin_error));
  const totalMae = mae(res.map((r) => r.total_error));
  const props = isLocked(h.props) ? null : h.props;
  return (
    <section aria-labelledby={`${league}-y`} className="space-y-4">
      <h2 id={`${league}-y`} className="font-display text-2xl font-700 text-ink">{league.toUpperCase()}</h2>
      {locked ? (
        <LockedPanel requires={lockedGate && isLocked(lockedGate) ? lockedGate.requires : "pro"}
          title="Recorded projections are on Pro" body="Final scores are below; the model's pre-game numbers and grades need Pro." />
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Games graded" value={`${graded.length} / ${h.games.length}`} note={graded.length < h.games.length ? "the rest aren't final or had no projection" : undefined} />
          <Stat label="Winner picked" value={winners.length ? `${winners.filter((r) => r.winner_correct).length} of ${winners.length}` : "–"} />
          <Stat label="Margin error (avg)" value={marginMae == null ? "–" : `${marginMae.toFixed(1)} pts`} />
          <Stat label="Total error (avg)" value={totalMae == null ? "–" : `${totalMae.toFixed(1)} pts`} />
          <Stat label="Vs market spread" value={recText(spread)} note={spread.w + spread.l + spread.p ? "model's side, W–L–push" : "no market line recorded"} />
          <Stat label="Vs market total" value={recText(total)} note={total.w + total.l + total.p ? "model's side, W–L–push" : "no market line recorded"} />
        </div>
      )}
      <ul className="divide-y divide-navy-700/70 overflow-hidden rounded-lg border border-navy-700 bg-navy-900">
        {h.games.map((g) => {
          const pre = g.pregame && !isLocked(g.pregame) ? g.pregame : null;
          const r = g.result && !isLocked(g.result) ? g.result : null;
          const m = g.market && !isLocked(g.market) ? g.market : null;
          return (
            <li key={g.game_id} className="grid gap-2 px-4 py-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1.2fr)] sm:items-center">
              <div className="space-y-1">
                {[{ t: g.away, s: g.final?.away, p: pre?.pred_away_score }, { t: g.home, s: g.final?.home, p: pre?.pred_home_score }].map((x) => (
                  <div key={x.t} className="flex items-center gap-2">
                    <TeamBadge league={league} abbr={x.t} size="sm" />
                    <span className="flex-1 font-600 text-ink">{x.t}</span>
                    <span className="w-10 text-right font-mono text-sm text-model" title="Model, before the game">{x.p != null ? formatNumber(x.p) : ""}</span>
                    <span className="w-10 text-right font-display text-lg font-700 text-ink">{x.s ?? "–"}</span>
                  </div>
                ))}
              </div>
              <div className="text-sm text-mute">
                {!g.final ? <span className="text-faint">Not final yet: not graded</span> : r ? (
                  <>
                    <div>Margin off by {Math.abs(r.margin_error).toFixed(1)}, total off by {Math.abs(r.total_error).toFixed(1)}</div>
                    {r.winner_correct != null ? <div className={r.winner_correct ? "text-good" : "text-danger"}>{r.winner_correct ? "Picked the winner" : "Missed the winner"}</div> : null}
                  </>
                ) : pre ? null : <span className="text-faint">No projection recorded before this game</span>}
              </div>
              <div className="space-y-0.5 text-sm">
                {m ? (
                  <>
                    {m.spread ? <PickLine label="Spread" home={g.home} away={g.away} p={m.spread} spread /> : null}
                    {m.total ? <PickLine label="Total" home={g.home} away={g.away} p={m.total} /> : null}
                    <div className="text-xs text-faint">Line: {m.source ?? "unknown source"}{m.captured_at ? `, ${formatTimestamp(m.captured_at)}` : ", capture time not published"}</div>
                  </>
                ) : g.market && isLocked(g.market) ? null : <span className="text-xs text-faint">No market line recorded</span>}
                {pre ? <div className="text-xs text-faint">Model {pre.model_version}, recorded {formatTimestamp(pre.generated_at)}</div> : null}
              </div>
            </li>
          );
        })}
      </ul>
      {props ? <PropsDay league={league} props={props} date={date} /> : null}
    </section>
  );
}

function PickLine({ label, p, home, away, spread = false }: { label: string; p: HistoryPick; home: string; away: string; spread?: boolean }) {
  const side = spread ? (p.pick === "home" ? `${home} ${fmtLine(p.line)}` : `${away} ${fmtLine(-p.line)}`) : `${p.pick === "over" ? "Over" : "Under"} ${p.line}`;
  const tone = p.result === "win" ? "text-good" : p.result === "loss" ? "text-danger" : "text-mute";
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <span className="text-faint">{label}</span>
      <span className="text-ink">{side}</span>
      <span className="font-mono text-xs text-model">{formatPct(p.model_prob)}</span>
      <span className={`font-600 ${tone}`}>{p.result ? p.result[0].toUpperCase() + p.result.slice(1) : "Pending"}</span>
    </div>
  );
}
const fmtLine = (x: number) => (x > 0 ? `+${x}` : `${x}`);

/** Props: projection error by category (players who played), and the ladder lines' hit rates vs the model. */
function PropsDay({ league, props, date }: { league: League; props: HistoryProp[]; date: string }) {
  const played = props.filter((p) => p.played);
  if (!props.length) return null;
  const cats = new Map<string, { label: string; err: number[]; ll: number[]; brier: number[] }>();
  for (const p of played) {
    for (const [k, m] of Object.entries(p.markets)) {
      if (m.actual == null) continue;
      const c = cats.get(k) ?? { label: m.label, err: [], ll: [], brier: [] };
      c.err.push(m.mean - m.actual);
      for (const t of m.thresholds) {
        if (t.hit == null) continue;
        const q = Math.min(Math.max(t.p, 1e-4), 1 - 1e-4);
        const y = t.hit ? 1 : 0;
        c.ll.push(-(y * Math.log(q) + (1 - y) * Math.log(1 - q)));
        c.brier.push((q - y) ** 2);
      }
      cats.set(k, c);
    }
  }
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const rows = [...cats.entries()].sort((a, b) => b[1].err.length - a[1].err.length);
  const focus = league === "nba" ? "points" : "receiving_yards";
  const top = played
    .filter((p) => p.markets[focus]?.actual != null)
    .sort((a, b) => (b.markets[focus].mean ?? 0) - (a.markets[focus].mean ?? 0))
    .slice(0, 12);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="overflow-x-auto rounded-lg border border-navy-700 bg-navy-900 p-4">
        <h3 className="mb-1 font-600 text-ink">Player props: projection error</h3>
        <p className="mb-3 text-xs text-faint">{played.length} players who played. Error = model mean − actual. Log loss and Brier score are over the model&apos;s own ladder lines (not market lines; no sportsbook prop prices are recorded yet).</p>
        <table className="w-full min-w-[26rem] text-sm">
          <thead className="text-faint"><tr><th className="py-1 text-left font-500">Prop</th><th className="py-1 text-right font-500">Players</th><th className="py-1 text-right font-500">Avg error</th><th className="py-1 text-right font-500">Bias</th><th className="py-1 text-right font-500">Log loss</th><th className="py-1 text-right font-500">Brier</th></tr></thead>
          <tbody>
            {rows.map(([k, c]) => (
              <tr key={k} className="border-t border-navy-700/70">
                <td className="py-1.5">{c.label}</td>
                <td className="py-1.5 text-right font-mono">{c.err.length}</td>
                <td className="py-1.5 text-right font-mono">{avg(c.err.map(Math.abs))!.toFixed(1)}</td>
                <td className="py-1.5 text-right font-mono">{fmtLine(Number(avg(c.err)!.toFixed(1)))}</td>
                <td className="py-1.5 text-right font-mono">{c.ll.length ? avg(c.ll)!.toFixed(3) : "–"}</td>
                <td className="py-1.5 text-right font-mono">{c.brier.length ? avg(c.brier)!.toFixed(3) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto rounded-lg border border-navy-700 bg-navy-900 p-4">
        <h3 className="mb-3 font-600 text-ink">{league === "nba" ? "Points" : "Receiving yards"}: top projections</h3>
        <table className="w-full min-w-[22rem] text-sm">
          <thead className="text-faint"><tr><th className="py-1 text-left font-500">Player</th><th className="py-1 text-right font-500">Model</th><th className="py-1 text-right font-500">Actual</th><th className="py-1 text-right font-500">Error</th></tr></thead>
          <tbody>
            {top.map((p) => {
              const m = p.markets[focus];
              return (
                <tr key={`${p.game_id}-${p.player_id}`} className="border-t border-navy-700/70">
                  <td className="py-1.5"><span className="text-ink">{p.player}</span> <span className="text-xs text-faint">{p.team}</span></td>
                  <td className="py-1.5 text-right font-mono text-model">{formatNumber(m.mean)}</td>
                  <td className="py-1.5 text-right font-mono text-ink">{formatNumber(m.actual!, 0)}</td>
                  <td className="py-1.5 text-right font-mono">{fmtLine(Number((m.mean - m.actual!).toFixed(1)))}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Link href={`/props?sport=${league}&date=${date}`} className="mt-3 inline-block text-sm font-600 text-model hover:underline">Every prop result for this day</Link>
      </div>
    </div>
  );
}
