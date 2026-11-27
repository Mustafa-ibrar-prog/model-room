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
  /** book_line: a posted sportsbook line; market_line: the consensus game line; model_line: a model threshold with no posted line. */
  source: "book_line" | "market_line" | "model_line";
  playerId?: string;
  playerName?: string;
  team?: string;
  support?: string | null;
  injury?: string | null;
  interpolated?: boolean;
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
  gameLabel: string;
  /** Model probability minus the market's no-vig probability (only for legs with a stored price). */
  edge: number | null;
  quality: "good" | "fair" | "thin";
  risk: "low" | "medium" | "high";
  score: number;
  why: string[];
  invalidators: string[];
}
