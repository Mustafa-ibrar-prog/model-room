/** Files written by `python -m modelroom history`. */
export interface HistoryIndex {
  league: string;
  first_recorded: string | null;
  generated_at: string;
  dates: { date: string; games: number; with_projection: number; props: number }[];
}

export interface HistoryGame {
  game_id: string;
  start_time: string | null;
  home: string;
  away: string;
  status: string;
  final: { home: number; away: number } | null;
  pregame: {
    generated_at: string;
    model_version: string;
    pred_home_score: number;
    pred_away_score: number;
    pred_margin: number;
    pred_total: number;
    home_win_prob: number;
  } | null;
  result: { margin_error: number; total_error: number; winner_correct: boolean | null } | null;
}

export interface HistoryProp {
  game_id: string;
  player_id: string;
  player: string;
  team: string;
  generated_at: string;
  model_version: string;
  played: boolean | null;
  markets: Record<string, { label: string; mean: number; sd: number; support: string | null; actual: number | null; thresholds: { k: number; p: number; hit: boolean | null }[] }>;
}

export interface HistoryDay {
  league: string;
  date: string;
  games: HistoryGame[];
  props: HistoryProp[];
}

export interface ProbBlock { n: number; brier: number; log_loss: number; avg_predicted: number; hit_rate: number }

export interface Performance {
  league: string;
  generated_at: string;
  note: string;
  games?: { n: number; margin_mae: number; total_mae: number; winner_correct: number | null; win_prob: ProbBlock; by_date: ({ date: string; margin_mae: number } & ProbBlock)[] };
  props?: {
    overall: ProbBlock;
    calibration: { bin: string; n: number; predicted: number; actual: number }[];
    by_market: Record<string, ProbBlock>;
    by_date: ({ date: string } & ProbBlock)[];
    by_player: ({ player: string } & ProbBlock)[];
  };
}
