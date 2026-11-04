import type { EngineAvailability, EngineGame } from "./engine";
/**
 * View types the pages render. Built on the server from engine board files
 * (src/types/engine.ts) and gated per plan in src/server/data.
 */

export type League = "nfl" | "nba";

export type TierId = "free" | "plus" | "pro";

/** A value the viewer's plan does not include. The real value is never sent. */
export type LockedValue = { locked: true; requires: TierId };

/** Either the real value or a lock marker, decided on the server. */
export type Gate<T> = T | LockedValue;

export function isLocked<T>(v: Gate<T>): v is LockedValue {
  return typeof v === "object" && v !== null && (v as LockedValue).locked === true;
}

export interface TeamRef {
  abbr: string;
  name: string;
}

export interface MarketView {
  spread: number | null;   // home team's line, negative = home favored
  total: number | null;
  homeMoneyline: number | null;
  awayMoneyline: number | null;
  books: number;
  capturedAt: string | null;
  sources: string[];
}

export interface GameView {
  id: string;
  league: League;
  startTime: string | null;
  gameDate: string;
  status: string;
  week: number | null;
  neutral: boolean;
  home: TeamRef;
  away: TeamRef;
  /** Model numbers on every plan. Spread uses the home team's line (negative = home favored). */
  modelSpread: number;
  modelTotal: number;
  projectedMargin: number;
  projectedScore: Gate<{ home: number; away: number }>;
  winProbability: Gate<{ home: number; away: number }>;
  ranges: Gate<{ margin: [number, number] | null; total: [number, number] | null }>;
  /** null = no market line for this game. */
  market: MarketView | null;
  spreadEdge: Gate<number | null>;
  totalEdge: Gate<number | null>;
  probabilityEdge: Gate<{ homeMarket: number; homeDiff: number } | null>;
  rest: { homeDays: number | null; awayDays: number | null; homeB2b: boolean; awayB2b: boolean };
  /** null = no injury feed for this league (not the same as no impact). */
  injuryAdjustment: Gate<number | null>;
  quarterbacks: { home: string | null; away: string | null } | null;
  qbAdjustment: Gate<number | null>;
  result: { homeScore: number; awayScore: number; margin: number; total: number } | null;
  /** Injury feed flags (null = no feed for this league this run; never read as "no injuries"). */
  availability: EngineAvailability | null;
  changes: EngineGame["changes"] | null;
}

export interface RatingView {
  rank: number;
  team: TeamRef;
  games: number;
  overall: number;
  overallUnit: string;
  avgMargin: number | null;
  last10Margin: number | null;
  components: Gate<{ key: string; label: string; value: number | null; unit: string; higherIsBetter: boolean | null }[]>;
}

export interface InjuryView {
  team: string;
  player: string;
  position: string | null;
  status: string | null;
  injury: string | null;
  practice: string | null;
  impactPoints: Gate<number | null>;
  impactNote: string | null;
  /** From the injury feed (test site): where the status came from and when. */
  source?: string | null;
  confirmed?: boolean;
  reportTime?: string | null;
  conflict?: string | null;
  lateScratch?: boolean;
  longTerm?: boolean;
}

export interface Freshness {
  status: "current" | "delayed" | "unavailable";
  reasons: string[];
  resultsThrough: string | null;
  lastIngest: string | null;
  modelRunAt: string | null;
}

export interface PerformanceView {
  backtest: {
    modelVersion: string;
    testSeasons: number[];
    games: number;
    marginMae: number;
    totalMae: number;
    totalBias: number;
    brier: number;
    winnerCorrect: number;
    baselines: { label: string; marginMae: number | null; totalMae: number | null }[];
    marketMarginMae: number | null;
    marketTotalMae: number | null;
    calibration: { bin: string; n: number; predicted: number; actual: number }[];
  } | null;
  seasonToDate: { games: number; marginMae: number; totalMae: number; winnerCorrect: number; note: string } | null;
  ledger: { tracked: number; graded: number; versions: { version: string; games: number; marginMae: number; totalMae: number; winnerCorrect: number }[] };
}

export type LeagueBoard =
  | {
      ok: true;
      league: League;
      seasonLabel: string;
      week: number | null;
      model: { version: string; status: string; fittedAt: string | null; uncertaintyMethod: string };
      freshness: Freshness;
      sources: string[];
      market: { connected: boolean; sources: string[]; note: string | null };
      injuries: { connected: boolean; note: string | null };
      upcoming: GameView[];
      recent: GameView[];
      recentPregame: Gate<Record<string, { margin: number; total: number; homeWinProb: number }>>;
      performance: PerformanceView;
    }
  | { ok: false; league: League; reason: string; freshness: Freshness };

/** Metadata attached to API responses. */
export interface DataEnvelope<T> {
  viewerTier: TierId;
  data: T;
}
