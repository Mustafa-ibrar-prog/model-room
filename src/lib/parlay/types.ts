/** Parlay Builder shapes shared by the server and the page (TEST, Moose 2026-11-27). No secrets, no model internals. */
import type { League } from "@/types/domain";

export type LegKind = "prop" | "spread" | "total" | "moneyline";

export interface BookPrice {
  american: number;
  /** Sportsbook key, when one book's price is shown. */
  book: string | null;
  bookTitle: string | null;
  /** Books quoting this exact line. */
  books: number;
  capturedAt: string | null;
}

/** A live Polymarket US quote matched EXACTLY to a leg (same player and team, stat, threshold and side). Prices are
 *  per $1 contract for this leg's side. Not stored anywhere; shown only in the TEST owner view. */
export interface PolymarketQuote {
  contract: string;
  /** Best bid / ask for this side (for an under / away leg: the NO side of the contract). */
  bid: number | null;
  ask: number | null;
  /** Mid of a two-sided book: the market's implied probability for this side. null when one-sided. */
  implied: number | null;
  spread: number | null;
  fee: number | null;
  status: string;
  /** Polymarket's own last update for the contract, and when we fetched it. */
  updatedAt: string | null;
  fetchedAt: string;
  /** Not in Polymarket's listing (needs one order-book request per contract): always null here. */
  liquidity: null;
}

/** One sportsbook's quote for a leg's market (its own line, which may differ from the leg's line). */
export interface BookQuote {
  book: string;
  title: string;
  line: number | null;
  /** Price for this leg's side at the book's line. */
  price: number | null;
  /** Price for the other side. */
  other: number | null;
  lastUpdate: string | null;
}

/** The player's last 10 played games against this leg's exact line (box scores; not the model's probability). */
export interface Last10 {
  games: number;
  hits: number;
  misses: number;
  pushes: number;
  avg: number;
  last5Hits: number;
  last5Games: number;
  values: number[];
  /** Per game, newest first: 1 hit, 0 push, -1 miss. */
  marks: number[];
  text: string;
}

/** One selectable leg. Every number here is computed on the server from stored data; the page never sends numbers back. */
export interface LegOption {
  id: string;
  league: League;
  gameId: string;
  kind: LegKind;
  label: string;
  group: string;
  /** Model probability the leg wins (pushes count as not winning). */
  p: number;
  push: number | null;
  /** Best stored sportsbook price for this exact line, or null (never estimated). */
  price: BookPrice | null;
  /** The market's own no-vig probability for this side, when stored. */
  marketP: number | null;
  /** book_line: a posted sportsbook line; market_line: the consensus game line; model_line: a model threshold with no
   *  posted line; exchange_line: a Polymarket US contract's line (owner view only). */
  source: "book_line" | "market_line" | "model_line" | "exchange_line";
  /** Live Polymarket US quote for exactly this outcome (owner view on TEST only; never stored). */
  polymarket?: PolymarketQuote | null;
  playerId?: string;
  playerName?: string;
  team?: string;
  support?: string | null;
  injury?: string | null;
  interpolated?: boolean;
  /** Every stored sportsbook quote for this market (book lines and game lines only). */
  quotes?: BookQuote[];
  /** The leg's line from this side's point of view (null for moneylines and model thresholds). */
  line?: number | null;
  /** When the newest stored quote was updated by its book. */
  updatedAt?: string | null;
  /** Why there is no price, in words (shown instead of a dash). */
  noPrice?: string | null;
  last10?: Last10 | null;
  /** Opponent and recent minutes / snaps, for the short AI note (from the board, never estimated). */
  context?: { opp?: string; usage?: string } | null;
}

export interface GameOption {
  league: League;
  gameId: string;
  start: string | null;
  home: string;
  away: string;
  label: string;
  props: boolean;
  lines: boolean;
}

export interface LegResult extends LegOption {
  gameLabel: string;
  warnings: string[];
}

export interface ParlayPrice {
  ok: boolean;
  error?: string;
  legs: LegResult[];
  rejected: { id: string; reason: string }[];
  /** Model probability that every leg wins, or null when the data can't support a single number. */
  p: number | null;
  /** Range: correlation uncertainty (and Fréchet bounds for any game block without measured correlations). */
  range: [number, number] | null;
  /** The legs multiplied as if unrelated, for comparison. */
  independent: number | null;
  /** p / independent: above 1 the legs tend to win together, below 1 they work against each other. */
  correlationEffect: number | null;
  fairAmerican: number | null;
  fairDecimal: number | null;
  /** Legs' stored prices multiplied, only when every leg has one. Books price same-game parlays their own way. */
  bookIfSeparate: { american: number | null; decimal: number; legsPriced: number } | null;
  method: string;
  warnings: { level: "info" | "caution" | "risk"; text: string }[];
  /** Same-game links between legs (indices into legs; coefficient oriented as 'more of each'). */
  pairs: { a: number; b: number; r: number; relation: string }[];
  dataAsOf: { label: string; at: string | null }[];
}

export interface Pick {
  leg: LegOption;
  /** Which market the model is compared with. Polymarket appears only in the TEST owner view. */
  benchmark: "sportsbook" | "polymarket";
  /** That market's implied probability for this side. */
  marketP: number | null;
  gameLabel: string;
  /** Model probability minus the market's no-vig probability (only for legs with a stored price). */
  edge: number | null;
  quality: "good" | "fair" | "thin";
  risk: "low" | "medium" | "high";
  score: number;
  why: string[];
  invalidators: string[];
}
