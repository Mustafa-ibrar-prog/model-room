import type { Metadata } from "next";
import { Suspense } from "react";
import { InjuryBoard } from "@/components/tables/InjuryBoard";
import { PageHeader, Section, TableSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Injury impact" };

export default function InjuriesPage() {
  return (
    <>
      <PageHeader
        title="Injury impact"
        intro="The latest status for every listed player. Plus shows how many points each absence moves the spread and the total."
      />
      <Section title="NFL">
        <Suspense fallback={<TableSkeleton />}>
          <InjuryBoard league="nfl" />
        </Suspense>
      </Section>
      <Section title="NBA">
        <Suspense fallback={<TableSkeleton />}>
          <InjuryBoard league="nba" />
        </Suspense>
      </Section>
    </>
  );
}
