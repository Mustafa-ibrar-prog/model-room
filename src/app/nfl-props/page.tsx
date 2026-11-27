import type { Metadata } from "next";
import { Suspense } from "react";
import { LeagueBrowse } from "@/components/league/Browse";
import Link from "next/link";
import { TableSkeleton } from "@/components/ui/primitives";
import { isProduction } from "@/lib/auth-config";

export const metadata: Metadata = { title: "NFL Props" };

type SP = Promise<Record<string, string | string[] | undefined>>;

/** NFL player projections: the games, the players in one of them, and one player in full. No game predictions here. */
export default function NflPropsPage({ searchParams }: { searchParams: SP }) {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 pb-16 pt-6 sm:px-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm font-600 text-model">NFL Props</p>
        {isProduction() ? null : <Link href="/parlay" className="text-sm font-600 text-mute hover:text-ink">Build a parlay</Link>}
      </div>
      <Suspense fallback={<TableSkeleton rows={6} />}>
        <LeagueBrowse league="nfl" searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
