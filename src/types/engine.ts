/**
 * Shape of the board files the Python engines publish (modeling/data/published/<league>.json).
 * Schema version 1. Server-only input; pages receive gated views from src/server/data.
 */
import type { League } from "./domain";

export interface EngineTeam {
  id: number | string;
  abbr: string;
  name: string;
  net_rating?: number | null;
  rating?: number | null;
}

export interface EngineProjection {
  home_score: number;
  away_score: number;
  margin: number;
  total: number;
  spread: number;
  home_win_prob: number;
  away_win_prob: number;
  margin_range_80: [number, number] | null;
  total_range_80: [number, number] | null;
}

export interface EngineMarket {
  spread: number | null;
  total: number | null;
  home_ml: number | null;
  away_ml: number | null;
  books: number;
  captured_at: string | null;
  sources: string[];
}

export interface EngineEdges {
  spread: number | null;
  total: number | null;
  home_prob_market: number | null;
  away_prob_market: number | null;
  home_prob_diff: number | null;
  /** Model probabilities at the market's own lines (engine common/board.market_detail). */
  implied_scores?: { home: number; away: number } | null;
  at_spread?: { line: number; home: EngineSide; away: EngineSide } | null;
  at_total?: { line: number; over: EngineSide; under: EngineSide } | null;
  moneyline?: { home: EngineSide; away: EngineSide } | null;
  by_book?: Record<string, { at_spread: EngineEdges["at_spread"]; at_total: EngineEdges["at_total"]; moneyline: EngineEdges["moneyline"]; captured_at: string | null; source: string | null }>;
}

export interface EngineSide {
  model_prob: number;
  push_prob: number;
  fair_odds: number | null;
  market_price: number | null;
  market_implied: number | null;
  ev_per_dollar: number | null;
}

export interface EngineGame {
  game_id: string;
  start_time: string | null;
  game_date: string;
  status: string;
  season_type?: string;
  week?: number;
  neutral: boolean;
  home: EngineTeam;
  away: EngineTeam;
  rest: { home_days: number | null; away_days: number | null; home_b2b?: boolean; away_b2b?: boolean };
  adjustments: { rest_points: number | null; injury_points: number | null; qb_points?: number | null };
  quarterbacks?: { home: string | null; away: string | null } | null;
  projection: EngineProjection;
  market: EngineMarket | null;
  edges: EngineEdges | null;
  result: { home_score: number; away_score: number; margin: number; total: number } | null;
  /** Injury feed flags for this game (test site): designated players per side, with source and time. */
  availability?: EngineAvailability | null;
  /** Why the projection moved since the previous published board (only when the injury picture changed). */
  changes?: { previous_at: string | null; reasons: string[]; moved: Record<string, { from: number; to: number }> } | null;
}

export interface EngineFlag {
  player: string;
  player_id: string;
  position: string | null;
  status: "out" | "doubtful" | "questionable" | "probable";
  raw_status: string | null;
  source: string;
  confirmed: boolean;
  report_time: string | null;
  detail: string | null;
  long_term: boolean;
  late_scratch: boolean;
  restriction: boolean;
  conflict: string | null;
}

export interface EngineAvailability {
  home: EngineFlag[];
  away: EngineFlag[];
  updated_at: string | null;
  sources: string[];
}

export interface EngineRatingComponent {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  higher_is_better: boolean | null;
}

export interface EngineRating {
  rank: number;
  team_id: number | string;
  abbr: string;
  name: string;
  games_played: number;
  overall: number;
  overall_unit: string;
  avg_margin: number | null;
  last10_margin: number | null;
  components: EngineRatingComponent[];
}

export interface EngineInjury {
  team: string;
  player: string;
  position: string | null;
  status: string | null;
  injury: string | null;
  practice: string | null;
  week: number | null;
  impact_points: number | null;
  impact_note: string | null;
}

export interface EngineBoard {
  schema_version: number;
  league: League;
  generated_at: string;
  season: number;
  season_label: string;
  week?: number | null;
  model: {
    id: string;
    version: string;
    params_hash: string;
    status: string;
    fitted_at: string | null;
    inputs_hash: string;
    uncertainty: { margin_sigma: number; total_sigma: number | null; method: string };
  };
  data: {
    sources: string[];
    freshness: { status: "current" | "delayed"; reasons: string[]; results_through: string | null; last_ingest: string | null };
    injuries: { connected: boolean; note: string | null; source?: string | null };
    market: { connected: boolean; sources: string[]; note: string | null };
  };
  upcoming: EngineGame[];
  recent: EngineGame[];
  ratings: EngineRating[];
  injuries?: EngineInjury[];
  performance: {
    backtest: null | {
      model_version: string;
      test_seasons: number[];
      games: number;
      margin_mae: number;
      total_mae: number;
      total_bias: number;
      brier: number;
      winner_correct: number;
      baselines: Record<string, number | null>;
      calibration: { bin: string; n: number; predicted: number; actual: number }[];
      market_comparison: unknown;
    };
    season_to_date: null | { games: number; margin_mae: number; total_mae: number; winner_correct: number; note: string };
    ledger: { tracked: number; graded: number; note?: string; by_version?: Record<string, { games: number; margin_mae: number; total_mae: number; winner_correct: number; brier: number }> };
  };
}
