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
  /** The market line the site had before the game, the model's side at it, and how that side settled. */
  market?: HistoryMarket | null;
}

export type Settle = "win" | "loss" | "push" | null;
export interface HistoryPick { line: number; pick: string; model_prob: number; push_prob: number; result: Settle }
export interface HistoryMarket {
  source: string | null;
  captured_at: string | null;
  implied_scores: { home: number; away: number } | null;
  spread: HistoryPick | null;
  total: HistoryPick | null;
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
  /** Picks frozen before each game and graded on the selected side (python -m modelroom history). */
  picks?: PickRow[];
}

export type PickResult = "hit" | "miss" | "push" | "void" | "cancelled" | "pending";

/** One stored pick and how it settled. The selection, line and team/player are as written before the game. */
export interface PickRow {
  id: string;
  game_id: string;
  market: "moneyline" | "spread" | "total" | "prop";
  selection: "home" | "away" | "over" | "under" | "at_least" | "below";
  team: string | null;
  /** Spread: the selected team's own line. Total: the market total. Prop: the threshold. Moneyline: null. */
  line: number | null;
  model_number: number | null;
  model_prob: number | null;
  model_version: string;
  recorded_at: string;
  /** True for picks reconstructed from pre-game records when the picks ledger was first created. */
  backfilled: boolean;
  /** True only when the pick itself was written before the game started. False: written afterwards from the projection recorded before it. */
  frozen_before_start?: boolean;
  result: PickResult;
  line_source?: string | null;
  line_books?: number | null;
  player?: string;
  player_id?: string;
  stat?: string;
  stat_label?: string;
  line_kind?: string | null;
  support?: string | null;
  actual?: number | null;
  played?: boolean | null;
  /** Set when the pick is left out of the official record: its prediction came from a version that was not published then. */
  excluded?: "unpublished_version" | null;
  /** The version that was published when an excluded pick's prediction was made. */
  published_version?: string | null;
}

export interface PickRecord { hit: number; miss: number; push: number; void: number; cancelled: number; pending: number; graded: number; hit_rate: number | null }

export interface PicksSummary {
  league: string;
  generated_at: string;
  note: string;
  overall: Record<"games" | "props" | "moneyline" | "spread" | "total" | "prop", PickRecord>;
  by_date: { date: string; games: PickRecord; props: PickRecord; moneyline?: PickRecord; spread?: PickRecord; total?: PickRecord }[];
  backfilled_picks: number;
  /** Per market: picks written before the game started, and picks written afterwards from the pre-game projection. */
  provenance?: Record<"moneyline" | "spread" | "total" | "prop", { pre_game: number; reconstructed: number }>;
  /** Picks kept for audit but left out of every official total. */
  excluded?: {
    total: number;
    rule: string;
    record: PickRecord;
    by_version: Record<string, number>;
    picks: { date: string; id: string; game_id: string; player: string | null; stat: string | null; stat_label: string | null; selection: string;
      line: number | null; model_version: string; published_version: string; recorded_at: string; frozen_before_start: boolean; result: PickResult }[];
  };
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
