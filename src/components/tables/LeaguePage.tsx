import { connection } from "next/server";
import Link from "next/link";
import { Suspense } from "react";
import type { League } from "@/types/domain";
import { DateNav } from "@/components/games/DateNav";
import { GameCards } from "@/components/games/GameCards";
import { HistoryGames } from "@/components/games/HistoryGames";
import { etDate, isDate } from "@/lib/dates";
import { getHistoryIndex } from "@/server/data/history";
import { GameBoard } from "./GameBoard";
import { InjuryBoard } from "./InjuryBoard";
import { ModelPerformance } from "./ModelPerformance";
import { RatingsBoard } from "./RatingsBoard";
import { ResultsBoard } from "./ResultsBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

const COPY: Record<League, { title: string; intro: string }> = {
  nfl: {
    title: "NFL",
    intro: "Upcoming games with the model's line, total, projected score and win probability, next to the market line where one is published.",
  },
  nba: {
    title: "NBA",
    intro: "The next three days of games with the model's line, total, projected score and win probability. Market lines appear when a line source is connected.",
  },
};

type SP = Promise<Record<string, string | string[] | undefined>>;

async function Games({ league, searchParams }: { league: League; searchParams: SP }) {
  const sp = await searchParams; // request-time from here, so the clock is per request
  await connection(); // the date is per request
  const today = etDate();
  const raw = typeof sp.date === "string" ? sp.date : undefined;
  const date = isDate(raw) && raw < today ? raw : null;
  const view = sp.view === "table" ? "table" : "cards";
  const index = await getHistoryIndex(league);
  const dates = (index?.dates ?? []).filter((d) => d.games > 0).map((d) => d.date);
  const tabs = "rounded-md px-3 py-1.5 text-sm";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <DateNav base={`/${league}`} date={date} dates={dates} today={today} params={view === "table" ? { view } : {}} />
        {!date ? (
          <div className="flex gap-1 rounded-md border border-navy-700 bg-navy-900 p-0.5" aria-label="Layout">
            <Link href={`/${league}`} className={`${tabs} ${view === "cards" ? "bg-navy-800 text-ink" : "text-mute"}`}>Cards</Link>
            <Link href={`/${league}?view=table`} className={`${tabs} ${view === "table" ? "bg-navy-800 text-ink" : "text-mute"}`}>Table</Link>
          </div>
        ) : null}
      </div>
      {date ? (
        <HistoryGames league={league} date={date} />
      ) : view === "table" ? (
        <GameBoard league={league} withinHours={league === "nba" ? 72 : undefined} />
      ) : (
        <GameCards league={league} withinHours={league === "nba" ? 72 : undefined} />
      )}
    </div>
  );
}

export function LeaguePage({ league, searchParams }: { league: League; searchParams: SP }) {
  return (
    <>
      <PageHeader title={COPY[league].title} intro={COPY[league].intro} />
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Suspense fallback={<TableSkeleton />}>
          <Games league={league} searchParams={searchParams} />
        </Suspense>
      </div>
      <Section title="Recent results" intro="Final scores next to what the model projected before each game.">
        <Suspense fallback={<TableSkeleton rows={6} />}>
          <ResultsBoard league={league} />
        </Suspense>
      </Section>
      <Section title="Model performance" intro="How far off the model has been, measured on games it never saw while being tuned.">
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <ModelPerformance league={league} />
        </Suspense>
      </Section>
      <Section title="Power ratings" intro="Current team strength from the same ratings the projections use.">
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <RatingsBoard league={league} limit={10} />
        </Suspense>
      </Section>
      <Section title="Injuries">
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <InjuryBoard league={league} limit={12} />
        </Suspense>
      </Section>
    </>
  );
}
