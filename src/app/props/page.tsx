import { connection } from "next/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { DateNav } from "@/components/games/DateNav";
import { Marketplace } from "@/components/market/Marketplace";
import { PropsHistory } from "@/components/props/PropsHistory";
import { etDate, isDate } from "@/lib/dates";
import { getHistoryIndex } from "@/server/data/history";
import { getUpcomingDates } from "@/server/data/upcoming";
import { PageHeader, TableSkeleton } from "@/components/ui/primitives";
import type { League } from "@/types/domain";

export const metadata: Metadata = { title: "Player props" };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default function PropsPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <div className="hidden sm:block"><PageHeader title="Player props" wide /></div>
      <h1 className="sr-only sm:hidden">Player props</h1>
      <div className="mx-auto max-w-[96rem] px-4 pb-16 pt-4 sm:px-6 sm:pt-0">
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <Explorer searchParams={searchParams} />
        </Suspense>
      </div>
    </>
  );
}

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

async function Explorer({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  // Older links: ?nfl=<game> / ?nba=<game> / ?game=<nfl game>.
  const league: League = one(sp.sport) === "nba" || (!one(sp.sport) && one(sp.nba)) ? "nba" : "nfl";
  const game = one(sp.game) ?? one(sp[league]);
  await connection(); // the date is per request
  const today = etDate();
  const raw = one(sp.date);
  const date = isDate(raw) ? raw : null;
  const past = date !== null && date < today;
  const [index, upcoming] = await Promise.all([getHistoryIndex(league), getUpcomingDates(league)]);
  const dates = (index?.dates ?? []).filter((d) => d.props > 0 || d.games > 0).map((d) => d.date);
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
      <div role="tablist" aria-label="Sport" className="flex gap-1 rounded-full bg-navy-850 p-1">
        {(["nfl", "nba"] as const).map((l) => (
          <Link
            key={l}
            role="tab"
            aria-selected={l === league}
            href={`/props?sport=${l}`}
            className={`rounded-full px-4 py-1 font-display text-sm font-600 uppercase tracking-wider sm:text-base ${l === league ? "bg-model text-navy-950" : "text-mute hover:text-ink"}`}
          >
            {l}
          </Link>
        ))}
      </div>
        <DateNav base="/props" params={{ sport: league }} date={date} dates={dates} upcoming={upcoming} today={today} />
      </div>
      {past && date ? (
        <PropsHistory league={league} date={date} game={game} cat={one(sp.cat)} q={one(sp.q)} />
      ) : (
        <Marketplace
          league={league}
          query={{ game, cat: one(sp.cat), q: one(sp.q), sort: one(sp.sort), team: one(sp.team), only: one(sp.only), line: one(sp.line), date: date ?? undefined }}
        />
      )}
    </>
  );
}
