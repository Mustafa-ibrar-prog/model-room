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
        intro="Power ratings in points against an average team on a neutral field. Pro adds offense, defense, pace and schedule strength."
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
