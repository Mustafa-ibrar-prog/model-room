import { connection } from "next/server";
import { Suspense } from "react";
import type { League } from "@/types/domain";
import { DateNav } from "@/components/games/DateNav";
import { GameRows } from "@/components/games/GameRows";
import { getUpcomingDates } from "@/server/data/upcoming";
import { HistoryGames } from "@/components/games/HistoryGames";
import { etDate, isDate } from "@/lib/dates";
import { getHistoryIndex } from "@/server/data/history";
import { InjuryBoard } from "./InjuryBoard";
import { ModelPerformance } from "./ModelPerformance";
import { RatingsBoard } from "./RatingsBoard";
import { ResultsBoard } from "./ResultsBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

const COPY: Record<League, { title: string; intro: string }> = {
  nfl: {
    title: "NFL",
    intro: "Model line, total and win chance for every game, next to the market line.",
  },
  nba: {
    title: "NBA",
    intro: "Model line, total and win chance for the next three days. Market lines appear when a line source is connected.",
  },
};

type SP = Promise<Record<string, string | string[] | undefined>>;

async function Games({ league, searchParams }: { league: League; searchParams: SP }) {
  const sp = await searchParams; // request-time from here, so the clock is per request
  await connection(); // the date is per request
  const today = etDate();
  const raw = typeof sp.date === "string" ? sp.date : undefined;
  const date = isDate(raw) ? raw : null;
  const [index, upcoming] = await Promise.all([getHistoryIndex(league), getUpcomingDates(league)]);
  const dates = (index?.dates ?? []).filter((d) => d.games > 0).map((d) => d.date);
  return (
    <div className="space-y-4">
      <DateNav base={`/${league}`} date={date} dates={dates} upcoming={upcoming} today={today} />
      {date && date < today ? (
        <HistoryGames league={league} date={date} />
      ) : (
        <GameRows league={league} day={date} withinHours={league === "nba" && !date ? 72 : undefined} />
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
