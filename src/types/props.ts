/**
 * Player-prop board written by `python -m modelroom nfl props` (modeling/data/published/nfl_props.json),
 * and the gated view the pages render.
 */
import type { Gate } from "@/types/domain";

export interface EngineQuoteView {
  provider: string;
  yes_bid: number | null;
  yes_ask: number | null;
  no_ask: number | null;
  mid: number | null;
  spread: number | null;
  ask_size: number | null;
  fee_yes: number | null;
  fee_no: number | null;
  ev_yes: number | null;
  ev_no: number | null;
  captured_at: string;
  usable: boolean;
  flags: string[];
}

export interface EngineBestSide {
  provider: string;
  price: number;
  fee: number | null;
  ev: number | null;
}

export interface EngineThreshold {
  op: ">=" | ">";
  threshold: number;
  variant: string | null;
  model_prob: number;
  model_prob_raw: number;
  quotes: EngineQuoteView[];
  best: { yes: EngineBestSide | null; no: EngineBestSide | null; edge: "yes" | "no" | null } | null;
  edge_grade: { grade: "strong" | "lean" | null; reasons: string[] };
}

export interface EnginePropMarket {
  label: string;
  mean: number;
  median: number;
  sd: number;
  support: "ok" | "limited" | "insufficient";
  support_note: string;
  range_80: [number, number];
  thresholds: EngineThreshold[];
}

export interface EnginePropPlayer {
  player_id: string;
  name: string;
  team: string;
  opp: string;
  position: string;
  game_id: string;
  injury_status: string | null;
  markets: Record<string, EnginePropMarket>;
  inputs: Record<string, number | string | null>;
}

export interface EnginePropsBoard {
  schema_version: number;
  league: string;
  kind: "player_props";
  generated_at: string;
  season: number;
  week: number | null;
  model: { id: string; version: string; status: string; fitted_at: string | null; sims: number };
  data: {
    last_ingest: string | null;
    results_through: string | null;
    markets: { provider: string; enabled: boolean; publishable: boolean; reason: string; quotes: number; last_captured_at: string | null }[];
    markets_not_published: { provider: string; reason: string }[];
    comparison_rules: { max_age_min: number; max_spread: number; min_size: number; min_ev: number };
  };
  performance: { backtest: PropBacktestSummary | null };
  games: {
    game_id: string;
    start_time: string | null;
    game_date: string;
    week: number;
    home: { abbr: string; name: string };
    away: { abbr: string; name: string };
    players: EnginePropPlayer[];
  }[];
}

export interface PropBacktestSummary {
  model_version: string;
  test_seasons: number[];
  thresholds: number;
  overall: { n: number; brier: number; log_loss: number } | null;
  overall_vs_baseline: { model: { log_loss: number; brier: number }; baseline: { log_loss: number; brier: number } } | null;
  by_market: Record<string, { log_loss: number; brier: number; n: number; baseline_log_loss: number | null; model_log_loss_same_rows: number | null; mean_mae: number; recent_avg_mae: number | null }>;
  calibration: { bin: string; n: number; predicted: number; actual: number }[] | null;
  notes: string[];
}

// ------------------------------------------------------------------ view

export interface PropLineView {
  op: ">=" | ">";
  threshold: number;
  variant: string | null;
  modelProb: number;
  /** Best usable market for this exact contract; null when no usable quote. */
  market: {
    provider: string;
    mid: number | null;
    bid: number | null;
    ask: number | null;
    spread: number | null;
    askSize: number | null;
    capturedAt: string;
    evYes: number | null;
    evNo: number | null;
  } | null;
  /** Every quote seen, including unusable ones, with the reasons. */
  quotes: { provider: string; mid: number | null; bid: number | null; ask: number | null; usable: boolean; flags: string[]; capturedAt: string }[];
  edge: { side: "yes" | "no"; provider: string; price: number; ev: number; grade: "strong" | "lean"; reasons: string[] } | null;
}

export interface PropMarketView {
  key: string;
  label: string;
  mean: number;
  median: number;
  sd: number;
  support: "ok" | "limited" | "insufficient";
  supportNote: string;
  range80: [number, number];
  lines: PropLineView[];
}

export interface PropPlayerView {
  id: string;
  name: string;
  team: string;
  opp: string;
  position: string;
  injuryStatus: string | null;
  markets: PropMarketView[];
  inputs: Gate<Record<string, number | string | null>>;
}

export interface PropGameView {
  id: string;
  startTime: string | null;
  home: { abbr: string; name: string };
  away: { abbr: string; name: string };
  players: PropPlayerView[];
}

export type PropsBoard =
  | { ok: false; reason: string }
  | {
      ok: true;
      generatedAt: string;
      week: number | null;
      model: { version: string; status: string; sims: number };
      markets: EnginePropsBoard["data"]["markets"];
      marketsNotPublished: EnginePropsBoard["data"]["markets_not_published"];
      rules: EnginePropsBoard["data"]["comparison_rules"];
      backtest: PropBacktestSummary | null;
      /** Every upcoming game (no player data), for the game picker. */
      schedule: { id: string; startTime: string | null; home: string; away: string; players: number }[];
      /** The selected game's players. Locked for plans without player props: no player data leaves the server. */
      game: Gate<PropGameView | null>;
      gameCount: number;
    };
