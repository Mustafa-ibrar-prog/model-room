import type { Metadata } from "next";
import { Suspense } from "react";
import { LeagueBrowse } from "@/components/league/Browse";
import { LeaguePage } from "@/components/tables/LeaguePage";
import { TableSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "NBA" };

type SP = Promise<Record<string, string | string[] | undefined>>;

/**
 * The NBA, in one place: the games, the players inside one of them, and one player in full.
 * `?view=games` keeps the game-level board (projected score, spread, total and the market comparison)
 * reachable; it is a view of this page rather than a separate item in the navigation.
 *
 * The page itself reads nothing from the request: searchParams are only awaited inside <Suspense>,
 * which is what this version of Next.js requires for a route to stay prerenderable.
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
      <LeagueBrowse league="nba" searchParams={Promise.resolve(sp)} />
    </div>
  );
}
