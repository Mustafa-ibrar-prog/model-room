import { Suspense } from "react";
import type { League } from "@/types/domain";
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

export function LeaguePage({ league }: { league: League }) {
  return (
    <>
      <PageHeader title={COPY[league].title} intro={COPY[league].intro} />
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Suspense fallback={<TableSkeleton />}>
          <GameBoard league={league} withinHours={league === "nba" ? 72 : undefined} />
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
