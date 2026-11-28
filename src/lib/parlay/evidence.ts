/** Evidence shapes shared by the server and the page (TEST, Moose 2026-11-28). */
export interface EvidenceItem {
  /** E1, E2, ... within one leg; the AI cites these. */
  id: string;
  kind: "model" | "form" | "usage" | "matchup" | "injury" | "lineup" | "environment" | "split" | "weather" | "market";
  text: string;
  source: string;
  /** When the data was current (ISO time or date), null when the source has no timestamp. */
  asOf: string | null;
  /** Which way it points for THIS leg's side, decided by fixed rules (never by the AI). */
  lean: "supports" | "against" | "neutral";
}
export interface LegEvidence { items: EvidenceItem[]; missing: string[] }

/** Page sections, in order. */
export const EVIDENCE_SECTIONS: { title: string; kinds: EvidenceItem["kind"][] }[] = [
  { title: "Model reasoning", kinds: ["model"] },
  { title: "Recent form", kinds: ["form", "split"] },
  { title: "Minutes and role", kinds: ["usage", "lineup"] },
  { title: "Matchup", kinds: ["matchup"] },
  { title: "Injuries and lineup", kinds: ["injury"] },
  { title: "Game environment", kinds: ["environment", "weather", "market"] },
];

/** Count of items for and against: a summary of the evidence, not a probability. */
export function evidenceBalance(e: LegEvidence | undefined): { supports: number; against: number } {
  const it = e?.items ?? [];
  return { supports: it.filter((x) => x.lean === "supports").length, against: it.filter((x) => x.lean === "against").length };
}
