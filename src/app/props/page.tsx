import type { Metadata } from "next";
import { Suspense } from "react";
import { PropBoard } from "@/components/tables/PropBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Player props" };

export default function PropsPage() {
  return (
    <>
      <PageHeader
        title="Player props"
        intro="Each player's posted line next to the model's projection. Pro adds the share of simulated outcomes over the line and the projected range."
      />
      <Section title="NFL">
        <Suspense fallback={<TableSkeleton />}>
          <PropBoard league="nfl" />
        </Suspense>
      </Section>
      <Section title="NBA">
        <Suspense fallback={<TableSkeleton />}>
          <PropBoard league="nba" />
        </Suspense>
      </Section>
    </>
  );
}
