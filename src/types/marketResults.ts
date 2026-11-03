/** data/published/market_results_<league>.json, written by `python -m modelroom markets settle`. */
export type SettleStatus = "won" | "lost" | "void" | "pending" | "no_call";

export interface MarketResult {
  id: string;
  league: string;
  kind: "prop" | "game";
  game_id: string | null;
  game_start: string | null;
  game_date: string | null;
  provider: string;
  market_id: string;
  market: string;
  market_label: string;
  op: ">=" | ">";
  threshold: number | null;
  variant: string | null;
  team: string | null;
  player: string | null;
  player_id: string | null;
  model_version: string;
  predicted_at: string;
  captured_at: string | null;
  model_prob: number;
  model_call: "yes" | "no" | null;
  market_bid: number | null;
  market_ask: number | null;
  market_implied: number | null;
  edge: { grade: string; side?: "yes" | "no"; result?: "won" | "lost" | null } | null;
  status: SettleStatus;
  settlement: {
    state: "settled" | "pending";
    result: "yes" | "no" | "void" | null;
    value: number | null;
    settled_at: string | null;
    settled_at_source: string | null;
    provider_status: string | null;
    note: string | null;
    observed_at: string;
    first_settled_at: string | null;
  } | null;
  corrections: { observed_at: string; result: string | null; was: string | null }[];
  projection: { mean?: number | null; sd?: number | null; margin?: number | null; total?: number | null; home?: string; away?: string } | null;
  actual: { stat?: number | null; home?: string; away?: string; home_score?: number; away_score?: number } | null;
}

export interface ResultBlock {
  predictions: number;
  settled: number;
  won: number;
  lost: number;
  void: number;
  pending: number;
  win_pct: number | null;
  n_scored?: number;
  brier?: number;
  log_loss?: number;
  market?: { n: number; brier: number; log_loss: number };
}

export interface MarketResultsFile {
  league: string;
  generated_at: string;
  note: string;
  providers: { provider: string; enabled: boolean; publishable: boolean; reason: string }[];
  withheld: Record<string, number>;
  records: MarketResult[];
}
