import type { Metadata } from "next";
import { Suspense } from "react";
import { PropBoard } from "@/components/tables/PropBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Player props" };

type Params = Promise<{ nfl?: string; nba?: string; game?: string }>;

export default function PropsPage({ searchParams }: { searchParams: Params }) {
  return (
    <>
      <PageHeader
        title="Player props"
        intro="The model's projection and probability for each player threshold, next to exchange prices where one is listed and usable."
      />
      <Section id="nfl" title="NFL">
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <SelectedGame league="nfl" searchParams={searchParams} />
        </Suspense>
      </Section>
      <Section id="nba" title="NBA">
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <SelectedGame league="nba" searchParams={searchParams} />
        </Suspense>
      </Section>
    </>
  );
}

async function SelectedGame({ league, searchParams }: { league: "nfl" | "nba"; searchParams: Params }) {
  const sp = await searchParams;
  const game = sp[league] ?? (league === "nfl" ? sp.game : undefined); // ?game= was the NFL-only link format
  return <PropBoard league={league} game={typeof game === "string" ? game : undefined} />;
}
