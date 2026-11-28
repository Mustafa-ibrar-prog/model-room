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

/** One player, one stat: the card the Parlay Builder shows (one per player per stat, never one per threshold). The
 *  page computes the selected threshold's numbers from these fields; the server re-derives every leg it prices. */
export interface PropCard {
  key: string;
  league: League;
  gameId: string;
  playerId: string;
  playerName: string;
  team: string;
  opp: string | null;
  market: string;
  label: string;
  noun: string;
  /** The model's mean for this stat (shown as a whole number). */
  projection: number;
  /** The model's calibrated P(stat >= k) at k = k0, k0 + step, ... */
  grid: { k0: number; step: number; p: number[] };
  /** Thresholds offered (K for "K or more" / "under K"): model grid points between 3% and 97%, plus market lines. */
  thresholds: number[];
  /** Sportsbook quotes for this player and stat (each book's own main line), and the line most books posted. */
  bookLine: number | null;
  quotes: { book: string; title: string; line: number; over: number | null; under: number | null; lastUpdate: string | null }[];
  /** Live Polymarket US "N+" contracts for exactly this player and stat (YES side prices). */
  pm: { line: number; bid: number | null; ask: number | null; status: string; updatedAt: string | null }[];
  pmFetchedAt: string | null;
  /** Last 10 played games for this stat, newest first. */
  values: number[] | null;
  injury: string | null;
  support: string | null;
  usage: string | null;
  /** Leg ids the catalog already lists for this player and stat (sportsbook-line and Polymarket-line legs carry prices). */
  legIds: string[];
}

export interface GameCard {
  league: League;
  gameId: string;
  kind: "spread" | "total" | "moneyline";
  home: string;
  away: string;
  /** The consensus line (home perspective for spreads). */
  consensus: number | null;
  /** Lines offered (home perspective for spreads): consensus, every book's own line and Polymarket's. */
  lines: number[];
  /** The engine's distribution: normal approximation from its projection and 80% range (as the engine does). */
  model: { mean: number; sd: number } | { homeWin: number };
  /** The engine's own published probabilities at the consensus line (home/over, away/under, push), used verbatim there. */
  atConsensus: { a: number; b: number; push: number } | null;
  /** The board's stored consensus prices for the consensus line / moneyline (used only when no single book quotes it). */
  consensusPrice: { a: number | null; b: number | null; books: number } | null;
  /** Each book's own line and prices (spreads: home line; home/away = home/away prices; totals: home = over, away = under). */
  books: { book: string; title: string; line: number | null; home: number | null; away: number | null; lastUpdate: string | null }[];
  /** Live Polymarket contracts (YES side). team: "home" / "away" (null for totals); spread line from that team's side. */
  pm: { team: "home" | "away" | null; line: number | null; bid: number | null; ask: number | null; status: string; updatedAt: string | null }[];
  pmFetchedAt: string | null;
}
