import type { Metadata } from "next";
import { PropBoard } from "@/components/tables/PropBoard";
import { PageHeader, Section } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Player props" };

export default function PropsPage() {
  return (
    <>
      <PageHeader title="Player props" intro="Each player's posted line next to a model projection, once the player models are built." />
      <Section title="NFL">
        <PropBoard league="nfl" />
      </Section>
      <Section title="NBA">
        <PropBoard league="nba" />
      </Section>
    </>
  );
}
