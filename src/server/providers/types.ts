import type { DailyInsight, InjuryStatus, League, Team } from "@/types/domain";

/**
 * Raw, ungated records as a provider produces them.
 * Providers are server-only. The data layer (src/server/data) gates these
 * per viewer before anything reaches a page or API response.
 */
export interface RawGame {
  id: string;
  league: League;
  slot: string;
  away: Team;
  home: Team;
  marketSpread: number;
  openingSpread: number;
  modelSpread: number;
  marketTotal: number;
  modelTotal: number;
  projectedScore: { away: number; home: number };
  matchupNote: string;
}

export interface RawInjury {
  id: string;
  league: League;
  player: string;
  team: Team;
  position: string;
  status: InjuryStatus;
  detail: string;
  spreadImpact: number;
  totalImpact: number;
}

export interface RawProp {
  id: string;
  league: League;
  player: string;
  team: Team;
  opponent: Team;
  market: string;
  line: number;
  projection: number;
  overShare: number;
  range: { low: number; high: number };
}

export interface RawRating {
  team: Team;
  league: League;
  overall: number;
  offense: number;
  defense: number;
  pace: number;
  scheduleStrength: number;
}

export interface ProviderInfo {
  source: "demo" | "live";
  name: string;
  note: string;
}

/** Anything that can supply Model Room data: the demo set today, the engines later. */
export interface DataProvider {
  info: ProviderInfo;
  getGames(league: League): Promise<RawGame[]>;
  getInjuries(league: League): Promise<RawInjury[]>;
  getProps(league: League): Promise<RawProp[]>;
  getRatings(league: League): Promise<RawRating[]>;
  getInsights(): Promise<DailyInsight[]>;
}
