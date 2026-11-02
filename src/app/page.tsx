import Link from "next/link";
import { Suspense } from "react";
import { Hero } from "@/components/marketing/Hero";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { DataSources } from "@/components/marketing/DataSources";
import { GameBoard } from "@/components/tables/GameBoard";
import { ModelPerformance } from "@/components/tables/ModelPerformance";
import { ResultsBoard } from "@/components/tables/ResultsBoard";
import { Section, TableSkeleton } from "@/components/ui/primitives";

const more = (href: string, label: string) => (
  <Link href={href} className="text-sm font-600 text-model hover:underline">
    {label}
  </Link>
);

export default function HomePage() {
  return (
    <>
      <Hero />

      <Section title="Next NFL games" intro="Model line and total next to the published market line." action={more("/nfl", "Full NFL board")}>
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <GameBoard league="nfl" limit={5} />
        </Suspense>
      </Section>

      <Section title="Next NBA games" intro="Model projections for the next games on the schedule." action={more("/nba", "Full NBA board")}>
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <GameBoard league="nba" limit={6} />
        </Suspense>
      </Section>

      <Section title="Recent results">
        <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
          <Suspense fallback={<TableSkeleton rows={5} />}>
            <ResultsBoard league="nfl" limit={6} />
          </Suspense>
          <Suspense fallback={<TableSkeleton rows={5} />}>
            <ResultsBoard league="nba" limit={6} />
          </Suspense>
        </div>
      </Section>

      <Section title="How the models are doing" intro="Measured on held-out seasons, then tracked game by game.">
        <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
          <Suspense fallback={<TableSkeleton rows={4} />}>
            <ModelPerformance league="nfl" compact />
          </Suspense>
          <Suspense fallback={<TableSkeleton rows={4} />}>
            <ModelPerformance league="nba" compact />
          </Suspense>
        </div>
      </Section>

      <HowItWorks />
      <DataSources />
    </>
  );
}
