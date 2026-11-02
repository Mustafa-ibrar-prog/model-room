/**
 * Core domain types shared by the data layer, API routes and UI.
 * These describe the *shape* of Model Room data. They carry no modeling logic.
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

export interface Team {
  id: string;
  abbr: string;
  city: string;
  name: string;
}

export interface GameProjection {
  id: string;
  league: League;
  /** Display-only slot label for the demo slate, e.g. "Sun 1:00 PM". */
  slot: string;
  away: Team;
  home: Team;
  /** Spreads are quoted from the home team's side: negative = home favored. */
  marketSpread: number;
  modelSpread: Gate<number>;
  spreadEdge: Gate<number>;
  marketTotal: number;
  modelTotal: Gate<number>;
  totalEdge: Gate<number>;
  projectedScore: Gate<{ away: number; home: number }>;
  openingSpread: Gate<number>;
  matchupNote: Gate<string>;
}

export type InjuryStatus = "Out" | "Doubtful" | "Questionable" | "Probable" | "Day-to-day";

export interface InjuryReport {
  id: string;
  league: League;
  player: string;
  team: Team;
  position: string;
  status: InjuryStatus;
  detail: string;
  /** Points of spread the model would move for this absence. */
  spreadImpact: Gate<number>;
  /** Change in the projected game total. */
  totalImpact: Gate<number>;
}

export interface PlayerPropProjection {
  id: string;
  league: League;
  player: string;
  team: Team;
  opponent: Team;
  market: string;
  line: number;
  projection: number;
  edge: number;
  /** Pro: share of simulated outcomes above the line. */
  overShare: Gate<number>;
  /** Pro: low/high of the projected range. */
  range: Gate<{ low: number; high: number }>;
}

export interface TeamRating {
  rank: number;
  team: Team;
  league: League;
  overall: number;
  offense: Gate<number>;
  defense: Gate<number>;
  pace: Gate<number>;
  scheduleStrength: Gate<number>;
}

export interface DailyInsight {
  id: string;
  league: League;
  title: string;
  body: string;
}

/** Metadata attached to every response so the UI can label demo data honestly. */
export interface DataMeta {
  source: "demo" | "live";
  generatedBy: string;
  note: string;
}

export interface DataEnvelope<T> {
  meta: DataMeta;
  viewerTier: TierId;
  data: T;
}
