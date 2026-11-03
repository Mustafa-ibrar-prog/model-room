import Link from "next/link";
import { Suspense } from "react";
import { Hero } from "@/components/marketing/Hero";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { DataSources } from "@/components/marketing/DataSources";
import { TopGaps } from "@/components/marketing/TopGaps";
import { GameRows } from "@/components/games/GameRows";
import { ModelPerformance } from "@/components/tables/ModelPerformance";
import { TableSkeleton } from "@/components/ui/primitives";

const more = (href: string, label: string) => (
  <Link href={href} className="text-sm font-600 text-model hover:underline">{label}</Link>
);

function Block({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="font-display text-xl font-700 text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function HomePage() {
  return (
    <>
      <Hero />
      {/* Phones: gaps first (the point of the site), then the next games, then the rest. Wide screens: two columns. */}
      <div className="mx-auto grid max-w-7xl gap-8 px-4 pb-10 sm:px-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="contents lg:block lg:space-y-8">
          <div className="order-2">
            <Block title="Next NFL games" action={more("/nfl", "All NFL")}>
              <Suspense fallback={<TableSkeleton rows={4} />}><GameRows league="nfl" limit={4} upcomingOnly note={false} /></Suspense>
            </Block>
          </div>
          <div className="order-3">
            <Block title="Next NBA games" action={more("/nba", "All NBA")}>
              <Suspense fallback={<TableSkeleton rows={4} />}><GameRows league="nba" limit={4} upcomingOnly note={false} /></Suspense>
            </Block>
          </div>
        </div>
        <div className="contents lg:block lg:space-y-8">
          <div className="order-1">
            <Block title="Biggest model vs market gaps">
              <Suspense fallback={<TableSkeleton rows={5} />}><TopGaps /></Suspense>
              <p className="mt-2 text-xs text-faint">Points between the model (blue) and the posted line (white). Orange: 3+ on a spread, 4+ on a total.</p>
            </Block>
          </div>
          <div className="order-4">
            <Block title="Player props" action={more("/props", "Open props")}>
              <div className="grid grid-cols-2 gap-2">
                <Link href="/props?sport=nfl" className="rounded-lg border border-navy-700 bg-navy-900 p-3 hover:border-model">
                  <div className="font-display text-lg font-700 text-ink">NFL props</div>
                  <div className="text-xs text-mute">Passing, rushing, receiving, TDs, fantasy</div>
                </Link>
                <Link href="/props?sport=nba" className="rounded-lg border border-navy-700 bg-navy-900 p-3 hover:border-model">
                  <div className="font-display text-lg font-700 text-ink">NBA props</div>
                  <div className="text-xs text-mute">Points, rebounds, assists, PRA, steals, blocks</div>
                </Link>
              </div>
            </Block>
          </div>
          <div className="order-5">
            <Block title="How the models are doing" action={more("/performance", "Performance")}>
              <div className="space-y-4">
                <Suspense fallback={<TableSkeleton rows={3} />}><ModelPerformance league="nfl" compact /></Suspense>
                <Suspense fallback={<TableSkeleton rows={3} />}><ModelPerformance league="nba" compact /></Suspense>
              </div>
            </Block>
          </div>
        </div>
      </div>
      <HowItWorks />
      <DataSources />
    </>
  );
}
