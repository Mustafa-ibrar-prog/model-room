import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { PerformanceTabs, type PerfTab } from "@/components/results/PerformanceTabs";
import { rateText, recordText } from "@/components/results/picks";
import { GameCard, PropsCard, ProvDot, RecordPanel } from "@/components/results/ResultCards";
import { PageHeader, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import { isDate, longDate, nowMs } from "@/lib/dates";
import { getPicksDay, getPicksSummary } from "@/server/data/history";
import type { League } from "@/types/domain";
import type { PickRecord } from "@/types/history";

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
  const href = (d: string | null) => `/performance?tab=${tab}${d ? `&date=${d}` : ""}`;
  const name = `${league.toUpperCase()}${isProps ? " player" : " game"}`;
  const o = summary?.overall;

  const now = nowMs();
  const dayRow = days[idx];
  const short = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  const weekday = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
  // Winner, spread and total are different bets and are never added into one percentage. A day is summarised
  // by its winner record on the games tabs; spread and total sit beside it when any were recorded.
  const dayMain = (d: (typeof days)[number]) => (isProps ? d.props : d.moneyline ?? d.games);
  const dayLine = (r: PickRecord) => (r.graded ? recordText(r) : r.pending ? "pending" : "\u2013");
  const games = (day?.games ?? []).filter((g) => picks.some((p) => p.game_id === g.game_id));
  const arrow = "inline-flex min-h-11 items-center rounded-lg border border-navy-700 px-3.5 text-sm text-mute hover:border-navy-600 hover:text-ink";

  return (
    <>
      <PerformanceTabs active={tab} />
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 pb-16 sm:px-6">
        {!summary || !o || !days.length ? (
          <Unavailable title={`No ${name} picks yet`} body="Picks appear here once a game the model made a pick on has started, and are graded when its final result is in." />
        ) : (
          <>
            {/* the record: settled picks only, each kind of pick on its own */}
            <div>
              {isProps ? (
                <RecordPanel label={`${league.toUpperCase()} player picks`} r={o.props} prov={summary.provenance?.prop} empty="No picks yet" />
              ) : (
                <div className="grid gap-2.5 md:grid-cols-3">
                  <RecordPanel label="Winner picks" r={o.moneyline} prov={summary.provenance?.moneyline} empty="No picks yet" />
                  <RecordPanel label="Spread picks" r={o.spread} prov={summary.provenance?.spread} empty="No recorded picks yet" />
                  <RecordPanel label="Total picks" r={o.total} prov={summary.provenance?.total} empty="No recorded picks yet" />
                </div>
              )}
              <div className="mt-2.5 space-y-1.5 rounded-xl border border-navy-700 px-4 py-3 text-xs leading-relaxed text-mute sm:px-5">
                <p>
                  Hit rate is hits divided by hits plus misses. Pushes, voids and pending picks are left out.
                  {isProps
                    ? " Each player pick is the model\u2019s own threshold nearest its projection, on the side it gave the better chance. No sportsbook line was published for these, so none is shown."
                    : " Winner, spread and total are separate records and are not added together."}
                </p>
                <p className="flex items-start gap-1.5">
                  <span className="mt-1"><ProvDot kind="pre_game" /></span>
                  <span><span className="font-600 text-ink">Recorded pre-game.</span> The pick was written before the game started.</span>
                </p>
                <p className="flex items-start gap-1.5">
                  <span className="mt-1"><ProvDot kind="reconstructed" /></span>
                  <span>
                    <span className="font-600 text-ink">Reconstructed.</span> The pick was written after the game started, from the projection the model recorded before it. It was not published before the game.
                    {isProps ? "" : " Spread and total picks are never reconstructed: without a side and a line stored before the game, the card says \u201cNo recorded pick\u201d."}
                  </span>
                </p>
              </div>
            </div>

            {/* which day */}
            <nav aria-label="Date" className="rounded-xl bg-navy-900">
              <div className="flex items-center justify-between gap-3 px-3 py-3 sm:px-4">
                {earlier ? <Link href={href(earlier)} className={arrow} aria-label={`Earlier: ${longDate(earlier)}`}>&larr;<span className="ml-1.5 hidden sm:inline">{short(earlier)}</span></Link> : <span className="w-12 sm:w-24" />}
                <div className="min-w-0 text-center">
                  <p className="font-display text-2xl font-600 leading-tight text-ink sm:text-[1.7rem]">{date ? longDate(date) : ""}</p>
                  {dayRow ? (
                    <p className="mt-0.5 text-sm text-mute">
                      {isProps ? (
                        <>{dayRow.props.graded ? <><span className="font-600 text-ink">{recordText(dayRow.props)}</span> &middot; {rateText(dayRow.props)} hit rate</> : "Nothing settled yet"}</>
                      ) : (
                        <>
                          Winner <span className="font-600 text-ink">{dayLine(dayMain(dayRow))}</span>
                          {dayRow.spread && dayRow.spread.graded + dayRow.spread.pending > 0 ? <> &middot; Spread <span className="font-600 text-ink">{dayLine(dayRow.spread)}</span></> : null}
                          {dayRow.total && dayRow.total.graded + dayRow.total.pending > 0 ? <> &middot; Total <span className="font-600 text-ink">{dayLine(dayRow.total)}</span></> : null}
                        </>
                      )}
                    </p>
                  ) : null}
                </div>
                {later ? <Link href={href(later)} className={arrow} aria-label={`Later: ${longDate(later)}`}><span className="mr-1.5 hidden sm:inline">{short(later)}</span>&rarr;</Link> : <span className="w-12 sm:w-24" />}
              </div>
              <div className="flex gap-1.5 overflow-x-auto border-t border-navy-700 px-3 py-2.5 sm:px-4" aria-label="Recent dates">
                {days.slice(-14).reverse().map((d) => (
                  <Link
                    key={d.date}
                    href={href(d.date)}
                    aria-current={d.date === date ? "date" : undefined}
                    className={`min-w-[4.4rem] shrink-0 rounded-lg px-2.5 py-1.5 text-center text-xs leading-tight ${d.date === date ? "bg-ink text-navy-950" : "text-mute hover:bg-navy-800 hover:text-ink"}`}
                  >
                    <span className="block text-[0.66rem] opacity-70">{weekday(d.date)}</span>
                    <span className="block font-600">{short(d.date)}</span>
                    <span className="block tabular-nums opacity-80">{dayLine(dayMain(d))}</span>
                  </Link>
                ))}
              </div>
            </nav>

            <div className="space-y-2.5">
              <p className="text-xs text-faint">{games.length} {games.length === 1 ? "game" : "games"}. Select a game to see {isProps ? "every player pick" : "the full prediction"}.</p>
              {games.map((g) =>
                isProps ? (
                  <PropsCard key={g.game_id} league={league} g={g} picks={picks.filter((p) => p.game_id === g.game_id)} now={now} />
                ) : (
                  <GameCard key={g.game_id} league={league} g={g} picks={picks.filter((p) => p.game_id === g.game_id)} now={now} />
                ),
              )}
            </div>

            <p className="text-xs leading-relaxed text-faint">
              HIT and MISS are decided by the stored side against the verified final {isProps ? "stat line" : "score"}, never by which side of the model&apos;s number the result fell.
              A result appears only once the final is in.
              {isProps ? " A player who did not play is VOID and is not counted." : ""}
              {" "}Past results do not predict future ones.
            </p>
          </>
        )}
      </div>
    </>
  );
}
