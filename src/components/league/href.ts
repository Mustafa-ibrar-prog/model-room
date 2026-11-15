import type { League } from "@/types/domain";

export interface BrowseQuery {
  game?: string;
  cat?: string;
  q?: string;
  player?: string;
}

/** A link into a league's player-props page, carrying only the parts that are set. */
export function browseHref(league: League, q: BrowseQuery): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v) p.set(k, String(v));
  const s = p.toString();
  return `/${league}-props${s ? `?${s}` : ""}`;
}
