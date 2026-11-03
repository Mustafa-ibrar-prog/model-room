import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { InjuryBoard } from "@/components/tables/InjuryBoard";
import { PageHeader, TableSkeleton } from "@/components/ui/primitives";
import type { League } from "@/types/domain";

export const metadata: Metadata = { title: "Injury impact" };

type SP = Promise<Record<string, string | string[] | undefined>>;
const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

export default function InjuriesPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader
        title="Injury impact"
        intro="Players with a game designation on the latest reports. Plus shows the projection change where the model accounts for an absence."
      />
      <div className="mx-auto max-w-7xl px-4 pb-16 sm:px-6">
        <Suspense fallback={<TableSkeleton />}>
          <Body searchParams={searchParams} />
        </Suspense>
      </div>
    </>
  );
}

async function Body({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const league: League = one(sp.sport) === "nba" ? "nba" : "nfl";
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Sport" className="inline-flex gap-1 rounded-full bg-navy-850 p-1">
        {(["nfl", "nba"] as const).map((l) => (
          <Link key={l} role="tab" aria-selected={l === league} href={`/injuries?sport=${l}`}
            className={`rounded-full px-4 py-1 font-display text-sm font-600 uppercase tracking-wider sm:text-base ${l === league ? "bg-model text-navy-950" : "text-mute hover:text-ink"}`}>
            {l}
          </Link>
        ))}
      </div>
      <InjuryBoard league={league} team={one(sp.team)} status={one(sp.status)} filters />
    </div>
  );
}
