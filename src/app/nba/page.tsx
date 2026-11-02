import type { Metadata } from "next";
import { LeaguePage } from "@/components/tables/LeaguePage";

export const metadata: Metadata = { title: "NBA projections" };

export default function NbaPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <LeaguePage league="nba" searchParams={searchParams} />;
}
