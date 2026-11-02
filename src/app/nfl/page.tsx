import type { Metadata } from "next";
import { LeaguePage } from "@/components/tables/LeaguePage";

export const metadata: Metadata = { title: "NFL projections" };

export default function NflPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <LeaguePage league="nfl" searchParams={searchParams} />;
}
