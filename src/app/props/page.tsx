import type { Metadata } from "next";
import { Suspense } from "react";
import { PropBoard } from "@/components/tables/PropBoard";
import { PageHeader, Section, TableSkeleton, Unavailable } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Player props" };

export default function PropsPage({ searchParams }: { searchParams: Promise<{ game?: string }> }) {
  return (
    <>
      <PageHeader
        title="Player props"
        intro="The model's projection and probability for each player threshold, next to exchange prices where one is listed and usable."
      />
      <Section title="NFL">
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <SelectedGame searchParams={searchParams} />
        </Suspense>
      </Section>
      <Section title="NBA">
        <Unavailable title="NBA player props aren't built yet" body="The NBA prop model comes after the NFL one is validated." />
      </Section>
    </>
  );
}

async function SelectedGame({ searchParams }: { searchParams: Promise<{ game?: string }> }) {
  const { game } = await searchParams;
  return <PropBoard league="nfl" game={typeof game === "string" ? game : undefined} />;
}
