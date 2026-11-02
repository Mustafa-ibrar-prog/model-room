import type { Metadata } from "next";
import { Suspense } from "react";
import { RatingsBoard } from "@/components/tables/RatingsBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Team ratings" };

export default function RatingsPage() {
  return (
    <>
      <PageHeader
        title="Team ratings"
        intro="Current team strength from the same ratings the projections use. Pro adds the offense, defense and schedule breakdown."
      />
      <Section title="NFL">
        <Suspense fallback={<TableSkeleton rows={10} />}>
          <RatingsBoard league="nfl" />
        </Suspense>
      </Section>
      <Section title="NBA">
        <Suspense fallback={<TableSkeleton rows={10} />}>
          <RatingsBoard league="nba" />
        </Suspense>
      </Section>
    </>
  );
}
