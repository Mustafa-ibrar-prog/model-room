import "server-only";
import { loadPerformanceFile, loadPropValidation, loadPropsBoard, loadBoard, loadLiveInjuries, loadRefreshStatus, type PropValidation, type RefreshStatus } from "@/server/engine/board";
import { connection } from "next/server";
import type { League } from "@/types/domain";
import { requireOwner } from "./access";
import { ownerQuery, type DbResult } from "./db";

/**
 * Owner dashboard loaders. Every one calls requireOwner() before reading anything. They only READ:
 * the published files the site already serves to itself, and (through the read-only role) the private odds tables.
 * Nothing is recalculated here: figures come as the refresh wrote them.
 */

// ------------------------------------------------------------------ private sportsbook report (odds.reports payload)
export interface LineObs { collected_at: string; book_updated_at: string; line: number | null; price_a: number | null; price_b: number | null; novig_a: number | null; hours_before_start: number | null }
export interface LineHistory {
  game_key: string; game_id: string | null; home: string; away: string; commence_time: string; sportsbook: string; market: string;
  side_a: string; side_b: string; observations: number; earliest_observed: LineObs; intermediate: LineObs[]; latest_observed: LineObs;
  latest_label: string; line_change: number | null; novig_a_change: number | null; direction: string;
}
export interface MoveAgg { series: number; series_with_2plus_observations: number; moved: number; mean_abs_line_change: number | null; mean_abs_novig_change_pp: number | null }
export interface Comparison {
  status: string; game_id: string; home: string; away: string; commence_time: string; sportsbook: string; market: string; side_a: string; side_b: string;
  line: number | null; price_a: number | null; price_b: number | null; book_novig_a: number | null; book_overround: number | null;
  collected_at: string; hours_before_start: number | null; model_version: string | null; model_generated_at: string;
  model_age_hours_at_line: number | null; model_prob_a_excl_push: number | null; model_prob_push: number | null; model_minus_book_novig_a_pp: number | null;
}
export interface SettledMarket { settled_games: number; required_for_summary: number; progress_pct: number; status?: string; model_log_loss?: number; book_novig_log_loss?: number; model_minus_book_log_loss?: number; model_minus_book_log_loss_95ci?: [number, number]; model_brier?: number; book_novig_brier?: number }
export interface PrivateReport {
  league: string; generated_at: string; notice?: string;
  accumulation?: {
    snapshot_rows: number; fetches: number; first_collected_at: string; last_collected_at: string; days_of_history: number; books: number; games: number;
    games_matched_to_schedule: number; series_game_book_market: number;
    comparisons: { matched: number; not_matched: Record<string, number>; rule: string };
    games_with_comparisons: { settled: number; upcoming_or_unsettled: number };
    odds_api?: { calls_logged: number; calls_this_month: number; credits_used_this_month_logged: number; credits_remaining_last_reported: string | number | null; as_of: string | null };
  };
  coverage?: { fetches: { collected_at: string; rows: number; games: number; books: number; game_book_pairs_missing_a_book: number; missing_market_slots: number; scheduled_games_next_72h_without_lines: number | null; stale_rows: number; unchanged_since_previous_fetch_rows: number }[]; rows_total: number; stale_rows_total: number; stale_rule: string; post_start_rows_excluded: number; markets_seen: string[] };
  movement?: { series?: number; overall?: MoveAgg; by_market?: Record<string, MoveAgg>; games_with_any_movement?: number; games_with_repeat_observations?: number };
  upcoming?: { status: string; games: number; comparisons: number; abs_model_minus_book_novig_pp: { median: number; p90: number } | null; note: string };
  settled?: Record<string, SettledMarket>;
  closing_line_value?: { status: string; reason: string; observations_within_close_window: number; close_window_minutes: number };
  // private only
  books_seen?: string[] | null;
  coverage_rows_by_book?: Record<string, number> | null;
  movement_by_book?: Record<string, MoveAgg> | null;
  line_histories?: LineHistory[];
  coverage_detail?: { missing_by_game: { fetch: string; game_key: string; missing_books: string[]; missing_markets_by_book: Record<string, string[]> }[]; stale_rows: { fetch: string; game_key: string; sportsbook: string; market: string; captured_at: string; book_age_hours: number }[] };
  upcoming_latest_comparisons?: Comparison[];
  settled_events?: unknown[];
}

export interface SportsbookData {
  report: { seq: number; insertedAt: string; runId: string | null; payload: PrivateReport } | null;
  runs: { seq: number; insertedAt: string; runId: string | null }[];
  comparisons: { rows: number; firstStoredAt: string | null; lastStoredAt: string | null };
  snapshots: { rows: number; firstStoredAt: string | null; lastStoredAt: string | null };
}

export async function loadSportsbook(league: League): Promise<DbResult<SportsbookData>> {
  return ownerQuery(async (tx) => {
    const latest = await tx<{ seq: number; inserted_at: Date; run_id: string | null; payload: string }[]>`
      select seq, inserted_at, run_id, payload from odds.reports where league = ${league} order by seq desc limit 1`;
    const runs = await tx<{ seq: number; inserted_at: Date; run_id: string | null }[]>`
      select seq, inserted_at, run_id from odds.reports where league = ${league} order by seq desc limit 12`;
    const [c] = await tx<{ n: number; first: Date | null; last: Date | null }[]>`
      select count(*)::int as n, min(inserted_at) as first, max(inserted_at) as last from odds.comparisons where league = ${league}`;
    const [s] = await tx<{ n: number; first: Date | null; last: Date | null }[]>`
      select count(*)::int as n, min(inserted_at) as first, max(inserted_at) as last from odds.snapshots where league = ${league}`;
    const iso = (d: Date | null) => (d ? new Date(d).toISOString() : null);
    return {
      report: latest[0] ? { seq: Number(latest[0].seq), insertedAt: iso(latest[0].inserted_at)!, runId: latest[0].run_id, payload: JSON.parse(latest[0].payload) as PrivateReport } : null,
      runs: runs.map((r) => ({ seq: Number(r.seq), insertedAt: iso(r.inserted_at)!, runId: r.run_id })),
      comparisons: { rows: c?.n ?? 0, firstStoredAt: iso(c?.first ?? null), lastStoredAt: iso(c?.last ?? null) },
      snapshots: { rows: s?.n ?? 0, firstStoredAt: iso(s?.first ?? null), lastStoredAt: iso(s?.last ?? null) },
    };
  });
}

export interface SchedulerHealth {
  last_dispatch: string | null; last_accepted: string | null; failures_24h: number; no_token_notes_24h: number; awaiting_response: number; token_stored: boolean; enabled: string;
  /** The wake plan: the scheduler starts a refresh run only once next_check_at has arrived. */
  next_check_at: string | null; next_check_reason: string | null; plan_updated_at: string | null;
  dispatches_since_update: number; minutes_overdue: number | null; plan_stale: boolean;
}

export async function loadSchedulerHealth(): Promise<DbResult<SchedulerHealth | null>> {
  return ownerQuery(async (tx) => {
    const r = await tx<Record<string, unknown>[]>`select * from scheduler.health`;
    if (!r[0]) return null;
    const iso = (d: unknown) => (d ? new Date(d as string).toISOString() : null);
    return {
      last_dispatch: iso(r[0].last_dispatch), last_accepted: iso(r[0].last_accepted), failures_24h: Number(r[0].failures_24h ?? 0),
      no_token_notes_24h: Number(r[0].no_token_notes_24h ?? 0), awaiting_response: Number(r[0].awaiting_response ?? 0),
      token_stored: Boolean(r[0].token_stored), enabled: String(r[0].enabled ?? "off"),
      next_check_at: iso(r[0].next_check_at), next_check_reason: r[0].next_check_reason ? String(r[0].next_check_reason) : null,
      plan_updated_at: iso(r[0].plan_updated_at), dispatches_since_update: Number(r[0].dispatches_since_update ?? 0),
      minutes_overdue: r[0].minutes_overdue == null ? null : Number(r[0].minutes_overdue), plan_stale: Boolean(r[0].plan_stale),
    };
  });
}

// ------------------------------------------------------------------ published files
export type RefreshStatusFull = RefreshStatus & {
  last_success_by_kind?: Record<string, { slot: string; status: string; at: string; note: string | null }>;
  missed?: { slot: string; due?: string; note?: string | null }[];
};

export interface PerformanceFile {
  generated_at: string;
  games?: { n: number; margin_mae?: number; total_mae?: number; winner_correct?: number; win_prob?: { n: number; brier: number; log_loss: number; avg_predicted: number; hit_rate: number } };
  props?: { overall?: { n: number; brier: number; log_loss: number; avg_predicted: number; hit_rate: number }; calibration?: { bin: string; n: number; predicted: number; actual: number }[] };
}

export interface OwnerFiles {
  validation: PropValidation | null;
  performance: PerformanceFile | null;
  refresh: RefreshStatusFull | null;
  boards: { games: { at: string; version: string } | null; props: { at: string; version: string } | null };
  injuriesAt: string | null;
}

export async function loadOwnerFiles(league: League): Promise<OwnerFiles> {
  await requireOwner();
  const [validation, performance, refresh, g, p, inj] = await Promise.all([
    loadPropValidation(league), loadPerformanceFile<PerformanceFile>(league), loadRefreshStatus() as Promise<RefreshStatusFull | null>,
    loadBoard(league), loadPropsBoard(league), loadLiveInjuries(league),
  ]);
  return {
    validation, performance, refresh,
    boards: {
      games: g.ok ? { at: g.board.generated_at, version: String((g.board as unknown as { model?: { version?: string } }).model?.version ?? "?") } : null,
      props: p.ok ? { at: p.board.generated_at, version: p.board.model.version } : null,
    },
    injuriesAt: inj?.generated_at ?? null,
  };
}

/** The request's clock (ages and staleness are relative to it); dynamic per request, never prerendered. */
export async function requestTime(): Promise<number> {
  await connection();
  return Date.now();
}
