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
        intro="Players with a game designation on the latest reports. Plus shows the projection change where the model accounts for an absence."
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
