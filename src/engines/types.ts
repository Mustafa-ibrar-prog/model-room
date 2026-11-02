/**
 * Modeling engine contracts.
 *
 * Engines are pure computation: they take validated inputs (schedules,
 * ratings inputs, injury lists, market lines) and return projections.
 * They must not import from src/app, src/components or React, and they never
 * decide what a viewer can see — the data layer does that.
 *
 * No algorithm is implemented in Phase 1. Each engine throws until it is
 * built and validated against historical results.
 */
import type { InjuryStatus, League } from "@/types/domain";

export interface ScheduledGame {
  gameId: string;
  league: League;
  startsAt: string; // ISO 8601
  homeTeamId: string;
  awayTeamId: string;
  venueId?: string;
}

export interface MarketSnapshot {
  gameId: string;
  spreadHome: number;
  total: number;
  capturedAt: string; // ISO 8601
  book: string;
}

export interface InjuryInput {
  playerId: string;
  teamId: string;
  status: InjuryStatus;
}

export interface EngineInput {
  games: ScheduledGame[];
  markets: MarketSnapshot[];
  injuries: InjuryInput[];
  asOf: string; // ISO 8601
}

export interface EngineGameOutput {
  gameId: string;
  modelSpreadHome: number;
  modelTotal: number;
  projectedHome: number;
  projectedAway: number;
  /** Engine version string so stored projections can be traced. */
  modelVersion: string;
}

export interface GameModelEngine {
  league: League;
  version: string;
  projectGames(input: EngineInput): Promise<EngineGameOutput[]>;
}

export class EngineNotImplementedError extends Error {
  constructor(league: League) {
    super(`The ${league.toUpperCase()} engine is not implemented yet. Phase 1 serves demo data only.`);
    this.name = "EngineNotImplementedError";
  }
}
