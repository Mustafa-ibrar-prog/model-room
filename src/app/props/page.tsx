import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { PropsExplorer } from "@/components/props/PropsExplorer";
import { PageHeader, TableSkeleton } from "@/components/ui/primitives";
import type { League } from "@/types/domain";

export const metadata: Metadata = { title: "Player props" };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default function PropsPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader
        title="Player props"
        intro="Pick a game, then a stat. Every player who matters for it, with the model's projection and the chance of each line, next to exchange prices where they're listed."
      />
      <div className="mx-auto max-w-7xl px-4 pb-16 sm:px-6">
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <Explorer searchParams={searchParams} />
        </Suspense>
      </div>
    </>
  );
}

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

async function Explorer({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  // Older links: ?nfl=<game> / ?nba=<game> / ?game=<nfl game>.
  const league: League = one(sp.sport) === "nba" || (!one(sp.sport) && one(sp.nba)) ? "nba" : "nfl";
  const game = one(sp.game) ?? one(sp[league]);
  return (
    <>
      <div role="tablist" aria-label="Sport" className="mb-5 flex gap-2">
        {(["nfl", "nba"] as const).map((l) => (
          <Link
            key={l}
            role="tab"
            aria-selected={l === league}
            href={`/props?sport=${l}`}
            className={`rounded-md border px-4 py-2 font-display text-base font-600 uppercase tracking-wider ${l === league ? "border-model bg-model text-navy-950" : "border-navy-700 bg-navy-900 text-ink"}`}
          >
            {l}
          </Link>
        ))}
      </div>
      <PropsExplorer
        league={league}
        query={{ game, cat: one(sp.cat), q: one(sp.q), sort: one(sp.sort), team: one(sp.team), only: one(sp.only) }}
      />
    </>
  );
}
