import { Suspense } from "react";
import type { League } from "@/types/domain";
import { GameBoard } from "./GameBoard";
import { InjuryBoard } from "./InjuryBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

const COPY: Record<League, { title: string; intro: string }> = {
  nfl: {
    title: "NFL",
    intro: "Every game on the slate with the posted spread and total, the model's numbers and the edge between them.",
  },
  nba: {
    title: "NBA",
    intro: "Tonight's games with the posted spread and total, the model's numbers and the edge between them.",
  },
};

export function LeaguePage({ league }: { league: League }) {
  return (
    <>
      <PageHeader title={COPY[league].title} intro={COPY[league].intro} />
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Suspense fallback={<TableSkeleton />}>
          <GameBoard league={league} />
        </Suspense>
        <p className="mt-3 text-sm text-faint">
          Spreads are shown from the home team&rsquo;s side. Negative means the home team is favored.
        </p>
      </div>
      <Section title="Injuries" intro="Status from the latest report and the projected effect on the line.">
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <InjuryBoard league={league} compact />
        </Suspense>
      </Section>
    </>
  );
}
