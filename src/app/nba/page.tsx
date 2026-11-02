import type { Metadata } from "next";
import { LeaguePage } from "@/components/tables/LeaguePage";

export const metadata: Metadata = { title: "NBA projections" };

export default function NbaPage() {
  return <LeaguePage league="nba" />;
}
