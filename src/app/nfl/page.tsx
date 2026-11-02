import type { Metadata } from "next";
import { LeaguePage } from "@/components/tables/LeaguePage";

export const metadata: Metadata = { title: "NFL projections" };

export default function NflPage() {
  return <LeaguePage league="nfl" />;
}
