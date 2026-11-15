import { fmt, lineLabel } from "@/components/market/bits";
import { marketMid, type ExplorerRow } from "@/server/data/explorer";
import type { PropLineView } from "@/types/props";

/**
 * The plain-English answer a card or a player page leads with.
 *
 * With no market line — which is every player prop today, because the only configured provider is the
 * manual CSV and it carries no quotes — the headline is the model's own threshold: "Chance of 20 or
 * more". That is a statement about the model's distribution, never an over/under against a market, and
 * nothing here invents a line, a price or a preferred side.
 */
export interface Headline {
  /** The threshold the probability is quoted at, as the ladder publishes it (20, 22.5…). */
  threshold: number;
  /** "20 or more" / "more than 20" — the comparison in words. */
  thresholdText: string;
  /** Model probability of clearing it. */
  prob: number;
  /** 1 − prob, as "Below 20". */
  belowProb: number;
  belowText: string;
  /** True when a market has actually quoted this exact contract. */
  fromMarket: boolean;
  /** The market's own implied probability, when there is one. */
  marketProb: number | null;
}

const nice = (n: number) => (Number.isInteger(n) ? n.toFixed(0) : n.toFixed(1));

/** The line a market has quoted for this player and stat, or null. Never the model's own ladder. */
export function marketLine(r: ExplorerRow): PropLineView | null {
  return r.headline && r.headline.quotes.length ? r.headline : null;
}

/**
 * Pick what to lead with: the quoted contract when a market has one, otherwise the model threshold
 * closest to the projection, which is the one a reader can sanity-check against the number beside it.
 */
export function headlineFor(r: ExplorerRow): Headline | null {
  const quoted = marketLine(r);
  const line =
    quoted ??
    [...r.ladder].sort((a, b) => Math.abs(a.threshold - r.mean) - Math.abs(b.threshold - r.mean))[0] ??
    null;
  if (!line) return null;
  const n = nice(line.threshold);
  return {
    threshold: line.threshold,
    thresholdText: line.op === ">=" ? `${n} or more` : `more than ${n}`,
    prob: line.modelProb,
    belowProb: 1 - line.modelProb,
    belowText: line.op === ">=" ? `below ${n}` : `${n} or less`,
    fromMarket: Boolean(quoted),
    marketProb: quoted ? marketMid(quoted) : null,
  };
}

/** How much history sits behind the projection, in words a reader can act on. Null when it is fine. */
export function historyCaveat(r: ExplorerRow): string | null {
  if (r.support === "ok") return null;
  const games = /^only (\d+) games/.exec(r.supportNote)?.[1];
  const much = r.support === "insufficient" ? "Very little" : "Limited";
  return games ? `${much} history — ${games} games on record` : `${much} history behind this number`;
}

/** "Knicks guard · vs IND" — who this is, without jargon. */
export function playerSub(r: ExplorerRow): string {
  const pos = r.position ? r.position : null;
  return [pos ? `${r.team} ${pos}` : r.team, `vs ${r.opp}`].join(" · ");
}

/** The projection, rounded the way the rest of the site rounds it. */
export const projText = (r: ExplorerRow) => fmt(r.mean);

/** "20+" / "Over 20.5" for a chip. */
export const chipLabel = lineLabel;

type Feed = { team: string; rows: { player: string; status: string }[] }[] | null;

/**
 * What the live injury feed says about this player, when it lists him out, doubtful or questionable.
 * The projection is made as if he plays, so a reader has to be told when the report says otherwise.
 */
export function listedStatus(feed: Feed, r: Pick<ExplorerRow, "name" | "team">): "out" | "doubtful" | "questionable" | null {
  const row = feed?.find((t) => t.team === r.team)?.rows.find((x) => x.player === r.name);
  return row && (row.status === "out" || row.status === "doubtful" || row.status === "questionable") ? row.status : null;
}

/** One sentence for that warning. */
export function listedText(status: "out" | "doubtful" | "questionable"): string {
  return status === "out"
    ? "Listed out on the injury report. This projection assumes he plays."
    : `Listed ${status} on the injury report. This projection assumes he plays.`;
}
