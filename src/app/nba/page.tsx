import type { Metadata } from "next";
import { Suspense } from "react";
import { GamePredictions } from "@/components/league/GamePredictions";
import { LeaguePage } from "@/components/tables/LeaguePage";
import { TableSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "NBA game predictions" };

type SP = Promise<Record<string, string | string[] | undefined>>;

/**
 * NBA game predictions: winner, score, total, margin and the model's read on the spread, one card per matchup.
 * Player projections live on the NBA Props page. `?view=games` keeps the older full board reachable.
 * searchParams are only awaited inside <Suspense>, which this version of Next.js requires.
 */
export default function NbaPage({ searchParams }: { searchParams: SP }) {
  return (
    <Suspense fallback={<div className="mx-auto w-full max-w-5xl px-4 pt-6 sm:px-6"><TableSkeleton rows={6} /></div>}>
      <View searchParams={searchParams} />
    </Suspense>
  );
}

async function View({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  if (sp.view === "games") return <LeaguePage league="nba" searchParams={Promise.resolve(sp)} />;
  return (
    <div className="mx-auto w-full max-w-5xl px-4 pb-16 pt-6 sm:px-6">
      <GamePredictions league="nba" />
    </div>
  );
}
