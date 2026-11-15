import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { PerformanceTabs, type PerfTab } from "@/components/results/PerformanceTabs";
import { modelText, outcomeText, pickText, rateText, recordText, RESULT_LABEL, tally, type GameCtx } from "@/components/results/picks";
import { PageHeader, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { isDate, longDate } from "@/lib/dates";
import { formatKickoff } from "@/lib/format";
import { getPicksDay, getPicksSummary } from "@/server/data/history";
import type { League } from "@/types/domain";
import type { HistoryGame, PickRecord, PickRow } from "@/types/history";

export const metadata: Metadata = { title: "Results" };

type SP = Promise<Record<string, string | string[] | undefined>>;

/**
 * Performance, for everyone: what the model picked before each game and what actually happened.
 * Every pick shown was stored before its game started; every result is graded on the side that was picked.
 * The technical record (Brier, log loss, calibration, model versions) lives under Stats for Nerds.
 */
export default function PerformancePage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader title="Performance" intro="What the model said before each game, next to what actually happened." />
      <Suspense fallback={<div className="mx-auto max-w-5xl px-4 sm:px-6"><TableSkeleton rows={8} /></div>}>
        <Results searchParams={searchParams} />
      </Suspense>
    </>
  );
}

const TONE: Record<PickRow["result"], string> = {
  hit: "bg-good/15 text-good",
  miss: "bg-danger/15 text-danger",
  push: "bg-navy-700 text-mute",
  void: "bg-navy-700 text-mute",
  cancelled: "bg-navy-700 text-mute",
  pending: "bg-navy-800 text-faint",
};

function Badge({ result }: { result: PickRow["result"] }) {
  return <span className={`inline-flex min-w-[4.25rem] justify-center rounded-md px-2 py-1 text-xs font-700 tracking-wide ${TONE[result]}`}>{RESULT_LABEL[result]}</span>;
}

const KIND: Record<string, string> = { moneyline: "Winner", spread: "Spread", total: "Total" };

function RecordTile({ label, r, big = false }: { label: string; r: PickRecord; big?: boolean }) {
  return (
    <div className={`rounded-xl bg-navy-900 ${big ? "p-5" : "px-4 py-3"}`}>
      <p className="text-xs text-faint">{label}</p>
      {r.graded ? (
        <>
          <p className={`font-display font-700 leading-none text-ink ${big ? "mt-1 text-5xl" : "mt-0.5 text-2xl"}`}>{recordText(r)}</p>
          <p className={`${big ? "mt-2 text-base" : "mt-0.5 text-sm"} text-mute`}>
            <span className="font-600 text-ink">{rateText(r)}</span>{big ? " hit rate" : ""}
          </p>
        </>
      ) : (
        <p className={`${big ? "mt-1 text-2xl" : "mt-0.5 text-base"} font-display font-600 text-faint`}>{big ? "No graded picks" : "None yet"}</p>
      )}
    </div>
  );
}

function notCounted(r: PickRecord): string | null {
  const parts = [r.pending ? `${r.pending} pending` : "", r.void ? `${r.void} void` : "", r.cancelled ? `${r.cancelled} cancelled` : ""].filter(Boolean);
  return parts.length ? `${parts.join(", ")} not counted` : null;
}

function Chevron() {
  return <svg viewBox="0 0 12 12" className="h-3 w-3 transition-transform group-open:rotate-180" aria-hidden="true"><path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
}

function GameHeader({ league, g }: { league: League; g: HistoryGame }) {
  const awayWon = g.final ? g.final.away > g.final.home : false;
  const homeWon = g.final ? g.final.home > g.final.away : false;
  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-navy-700 px-4 py-3.5 sm:px-5">
      <div className="flex items-center gap-2.5">
        <TeamBadge league={league} abbr={g.away} size="sm" />
        <span className={`font-display text-2xl font-700 leading-none ${awayWon ? "text-ink" : "text-mute"}`}>{g.final ? g.final.away : "\u2013"}</span>
        <span className="text-faint">@</span>
        <TeamBadge league={league} abbr={g.home} size="sm" />
        <span className={`font-display text-2xl font-700 leading-none ${homeWon ? "text-ink" : "text-mute"}`}>{g.final ? g.final.home : "\u2013"}</span>
      </div>
      <p className="ml-auto text-xs text-faint">
        {g.final ? "Final" : /postpon|cancel/i.test(g.status) ? "Not played" : "No final yet"}
        {g.start_time ? ` \u00b7 ${formatKickoff(g.start_time)}` : ""}
      </p>
    </header>
  );
}

/** A game: the picks that were stored before it, graded, and the projected score beside the real one. */
function GameCard({ league, g, picks }: { league: League; g: HistoryGame; picks: PickRow[] }) {
  const ctx: GameCtx = { home: g.home, away: g.away, final: g.final };
  const pre = g.pregame;
  return (
    <article className="overflow-hidden rounded-xl bg-navy-900">
      <GameHeader league={league} g={g} />
      {picks.length ? (
        <ul>
          <li className="hidden grid-cols-[5rem_1fr_1fr_auto] gap-3 px-5 pt-3 text-[0.7rem] text-faint sm:grid">
            <span />
            <span>Model picked</span>
            <span>What happened</span>
            <span className="w-[4.25rem]" />
          </li>
          {picks.map((p) => (
            <li key={p.id} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 border-b border-navy-800 px-4 py-3 last:border-b-0 sm:grid-cols-[5rem_1fr_1fr_auto] sm:px-5">
              <span className="col-span-2 text-[0.7rem] text-faint sm:col-span-1 sm:text-xs">{KIND[p.market]}</span>
              <span className="min-w-0">
                <span className="block text-[1.05rem] font-600 text-ink">{pickText(p)}</span>
                {modelText(p) ? <span className="block text-xs text-model">{modelText(p)}</span> : null}
                {p.market !== "moneyline" ? (
                  <span className="block text-[0.7rem] text-faint">
                    {p.line_books ? `pre-game line, ${p.line_books} sportsbooks` : "pre-game line"}
                  </span>
                ) : null}
              </span>
              <span className="row-start-3 text-sm text-mute sm:row-start-auto">{outcomeText(p, ctx)}</span>
              <span className="row-span-2 row-start-2 self-center sm:row-span-1 sm:row-start-auto"><Badge result={p.result} /></span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-3 text-sm text-faint sm:px-5">No pick was recorded before this game.</p>
      )}
      {/* a projected score is a projection, not a bet: shown with its error, never as a hit or a miss */}
      {pre ? (
        <dl className="grid grid-cols-3 gap-3 border-t border-navy-700 px-4 py-3 text-sm sm:px-5">
          <div>
            <dt className="text-[0.7rem] text-faint">Projected score</dt>
            <dd className="font-mono text-model">{pre.pred_away_score.toFixed(1)} &ndash; {pre.pred_home_score.toFixed(1)}</dd>
          </div>
          <div>
            <dt className="text-[0.7rem] text-faint">Actual score</dt>
            <dd className="font-mono text-ink">{g.final ? `${g.final.away} \u2013 ${g.final.home}` : "pending"}</dd>
          </div>
          <div>
            <dt className="text-[0.7rem] text-faint">Projection error</dt>
            <dd className="text-mute">
              {g.result ? `margin off by ${Math.abs(g.result.margin_error).toFixed(1)}, total off by ${Math.abs(g.result.total_error).toFixed(1)}` : "pending"}
            </dd>
          </div>
        </dl>
      ) : null}
    </article>
  );
}

/** A game's player picks: who, the line and side that were stored, what he finished with, and the grade. */
function PropsCard({ league, g, picks }: { league: League; g: HistoryGame; picks: PickRow[] }) {
  const ctx: GameCtx = { home: g.home, away: g.away, final: g.final };
  const rec = tally(picks.map((p) => p.result));
  const byPlayer = new Map<string, PickRow[]>();
  for (const p of picks) byPlayer.set(p.player_id ?? "", [...(byPlayer.get(p.player_id ?? "") ?? []), p]);
  return (
    <article className="overflow-hidden rounded-xl bg-navy-900">
      <GameHeader league={league} g={g} />
      <details className="group">
        <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm sm:px-5 [&::-webkit-details-marker]:hidden">
          <span className="font-500 text-ink">{byPlayer.size} players &middot; {picks.length} picks</span>
          <span className="flex items-center gap-2 text-mute">
            {rec.graded ? <><span className="font-600 text-ink">{recordText(rec)}</span> &middot; {rateText(rec)}</> : rec.pending ? "pending" : "none graded"}
            <Chevron />
          </span>
        </summary>
        <div className="px-4 pb-4 sm:px-5">
          <div className="hidden grid-cols-[1.2fr_1fr_1fr_auto] gap-3 pb-1 text-[0.7rem] text-faint sm:grid">
            <span>Player</span><span>Model picked</span><span>Final stat</span><span className="w-[4.25rem]" />
          </div>
          <ul>
            {[...byPlayer.values()].flatMap((rows) =>
              rows.map((p, i) => (
                <li key={p.id} className={`grid grid-cols-[1fr_auto] items-center gap-x-3 py-2 sm:grid-cols-[1.2fr_1fr_1fr_auto] ${i === 0 ? "border-t border-navy-700" : ""}`}>
                  <span className={`col-span-2 text-sm sm:col-span-1 ${i === 0 ? "font-600 text-ink" : "hidden sm:block sm:text-transparent"}`}>
                    {p.player} <span className="font-400 text-faint">{i === 0 ? p.team : ""}</span>
                  </span>
                  <span className="text-sm text-ink">
                    {pickText(p)}
                    {p.model_prob != null ? <span className="text-xs text-model"> &middot; {Math.round(p.model_prob * 100)}%</span> : null}
                  </span>
                  <span className="row-start-3 text-sm text-mute sm:row-start-auto">{outcomeText(p, ctx)}</span>
                  <span className="row-span-2 row-start-2 self-center sm:row-span-1 sm:row-start-auto"><Badge result={p.result} /></span>
                </li>
              )),
            )}
          </ul>
        </div>
      </details>
    </article>
  );
}

async function Results({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);
  const raw = one(sp.tab) ?? (one(sp.sport) === "nfl" ? "nfl" : one(sp.sport) === "nba" ? "nba" : "nba-props");
  const tab: Exclude<PerfTab, "stats"> = raw === "nfl-props" || raw === "nba" || raw === "nfl" ? raw : "nba-props";
  const league: League = tab.startsWith("nfl") ? "nfl" : "nba";
  const isProps = tab.endsWith("-props");
  const rec = (d: { games: PickRecord; props: PickRecord }) => (isProps ? d.props : d.games);
  const count = (r: PickRecord) => r.graded + r.pending + r.void + r.cancelled;

  const summary = await getPicksSummary(league);
  const days = (summary?.by_date ?? []).filter((d) => count(rec(d)) > 0);
  // Open on the latest day with something graded; a day that is all pending is not a result yet.
  const latestGraded = [...days].reverse().find((d) => rec(d).graded > 0)?.date ?? days.at(-1)?.date ?? null;
  const asked = one(sp.date);
  const date = isDate(asked) && days.some((d) => d.date === asked) ? asked : latestGraded;
  const idx = days.findIndex((d) => d.date === date);
  const earlier = idx > 0 ? days[idx - 1].date : null;
  const later = idx >= 0 && idx < days.length - 1 ? days[idx + 1].date : null;
  const day = date ? await getPicksDay(league, date) : null;
  const picks = (day?.picks ?? []).filter((p) => (p.market === "prop") === isProps);
  const today = days[idx] ? rec(days[idx]) : null;
  const href = (d: string | null) => `/performance?tab=${tab}${d ? `&date=${d}` : ""}`;
  const name = `${league.toUpperCase()}${isProps ? " player" : " game"}`;
  const o = summary?.overall;

  return (
    <>
      <PerformanceTabs active={tab} />
      <div className="mx-auto w-full max-w-5xl space-y-7 px-4 pb-16 sm:px-6">
        {!summary || !o || !days.length ? (
          <Unavailable title={`No ${name} picks yet`} body="Picks appear here once a game the model made a pick on has started, and are graded when its final result is in." />
        ) : (
          <>
            {/* the record, from settled picks only */}
            <section aria-label="Overall record">
              {isProps ? (
                <div className="grid gap-2.5 sm:grid-cols-[1.4fr_2fr]">
                  <RecordTile label={`All ${name} picks`} r={o.props} big />
                  <p className="self-center text-sm leading-relaxed text-mute">
                    Each pick is the model&apos;s own threshold nearest its projection, on the side it gave the better chance: &ldquo;20+ points&rdquo; or &ldquo;Under 20 points&rdquo;.
                    No sportsbook line was published for these props, so none is shown.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-[1.4fr_1fr_1fr_1fr]">
                  <div className="col-span-3 sm:col-span-1"><RecordTile label={`All ${name} picks`} r={o.games} big /></div>
                  <RecordTile label="Winner" r={o.moneyline} />
                  <RecordTile label="Spread" r={o.spread} />
                  <RecordTile label="Total" r={o.total} />
                </div>
              )}
              <p className="mt-2.5 text-sm text-faint">
                Only settled picks count toward the record. {notCounted(isProps ? o.props : o.games) ? `${notCounted(isProps ? o.props : o.games)}.` : ""}
                {!isProps && !o.spread.graded && !o.total.graded ? " Spread and total picks are graded only when the side and the line were stored before the game; that record starts with the first games after this page launched." : ""}
              </p>
            </section>

            {/* which day */}
            <nav aria-label="Date" className="flex items-center justify-between gap-3">
              {earlier ? <Link href={href(earlier)} className="min-h-11 rounded-lg border border-navy-700 px-3.5 py-2.5 text-sm text-mute hover:text-ink">&larr; Earlier</Link> : <span className="w-24" />}
              <div className="text-center">
                <p className="font-display text-2xl font-600 leading-tight text-ink">{date ? longDate(date) : ""}</p>
                {today ? (
                  <p className="text-sm text-mute">
                    {today.graded ? <><span className="font-600 text-ink">{recordText(today)}</span> &middot; {rateText(today)}</> : "Nothing graded yet"}
                    {notCounted(today) ? <span className="text-faint"> &middot; {notCounted(today)}</span> : null}
                  </p>
                ) : null}
              </div>
              {later ? <Link href={href(later)} className="min-h-11 rounded-lg border border-navy-700 px-3.5 py-2.5 text-sm text-mute hover:text-ink">Later &rarr;</Link> : <span className="w-24" />}
            </nav>
            <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" aria-label="Recent dates">
              {days.slice(-14).reverse().map((d) => (
                <Link
                  key={d.date}
                  href={href(d.date)}
                  aria-current={d.date === date ? "date" : undefined}
                  className={`shrink-0 rounded-lg border px-3 py-1.5 text-center text-xs ${d.date === date ? "border-ink bg-ink text-navy-950" : "border-navy-700 text-mute hover:border-navy-600"}`}
                >
                  <span className="block font-600">{new Date(`${d.date}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}</span>
                  <span className="block opacity-80">{rec(d).graded ? recordText(rec(d)) : rec(d).pending ? "pending" : "\u2013"}</span>
                </Link>
              ))}
            </div>

            <div className="space-y-3">
              {(day?.games ?? []).filter((g) => picks.some((p) => p.game_id === g.game_id)).map((g) =>
                isProps ? (
                  <PropsCard key={g.game_id} league={league} g={g} picks={picks.filter((p) => p.game_id === g.game_id)} />
                ) : (
                  <GameCard key={g.game_id} league={league} g={g} picks={picks.filter((p) => p.game_id === g.game_id)} />
                ),
              )}
            </div>

            <p className="text-xs leading-relaxed text-faint">
              A pick is a side the model&apos;s projection favoured before the game, stored then and never changed.
              HIT and MISS are decided by the stored side against the verified final {isProps ? "stat line" : "score"}, never by which side of the model&apos;s number the result fell.
              {isProps ? " A player who did not play is VOID and is not counted." : " A projected score is a projection, not a bet, so it is shown with its error instead of a grade."}
              {picks.some((p) => p.backfilled) ? " Picks on this date were written to the picks record from the pre-game prediction ledger when that record was first created." : ""}
              {" "}Past results do not predict future ones.
            </p>
          </>
        )}
      </div>
    </>
  );
}
