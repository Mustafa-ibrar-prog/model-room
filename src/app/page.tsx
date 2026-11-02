import Link from "next/link";
import { Suspense } from "react";
import { Hero } from "@/components/marketing/Hero";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { DataSources } from "@/components/marketing/DataSources";
import { GameBoard } from "@/components/tables/GameBoard";
import { InjuryBoard } from "@/components/tables/InjuryBoard";
import { DailyInsights } from "@/components/tables/DailyInsights";
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

      <Section title="NFL board" intro="Market lines, model lines and the edge between them." action={more("/nfl", "Full NFL board")}>
        <Suspense fallback={<TableSkeleton rows={3} />}>
          <GameBoard league="nfl" limit={3} />
        </Suspense>
      </Section>

      <Section title="Daily insights" intro="Short notes on the games where the model and the market are furthest apart.">
        <Suspense fallback={<TableSkeleton rows={2} />}>
          <DailyInsights />
        </Suspense>
      </Section>

      <Section title="Injury impact" intro="Who is out, and how far each absence moves the line." action={more("/injuries", "All injuries")}>
        <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
          <Suspense fallback={<TableSkeleton rows={4} />}>
            <InjuryBoard league="nfl" compact />
          </Suspense>
          <Suspense fallback={<TableSkeleton rows={4} />}>
            <InjuryBoard league="nba" compact />
          </Suspense>
        </div>
      </Section>

      <HowItWorks />
      <DataSources />

      <section className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
        <div className="flex flex-col items-start justify-between gap-5 rounded-2xl border border-navy-700 bg-navy-900 p-6 sm:flex-row sm:items-center sm:p-8">
          <div>
            <h2 className="font-display text-3xl font-700 text-ink">Free covers the basics.</h2>
            <p className="mt-1.5 max-w-xl text-mute">
              Plus adds the full Edge Finder, player props and injury adjustments. Pro adds history, alerts and reports.
            </p>
          </div>
          <Link href="/pricing" className="shrink-0 rounded-full bg-model px-5 py-2.5 font-600 text-navy-950 hover:bg-model/90">
            Compare plans
          </Link>
        </div>
      </section>
    </>
  );
}
