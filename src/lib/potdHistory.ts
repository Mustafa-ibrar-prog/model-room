/**
 * Pick of the Day results dashboard (TEST, Moose 2026-11-24): pure helpers over data/published/potd_history.json, which
 * `python -m modelroom potd` builds from the two append-only ledgers (picks frozen before tip-off, grades written after).
 * Nothing here estimates, rebuilds or backfills a pick. Win rate = wins / (wins + losses); pushes, voids and pending picks
 * are left out. The all-time record is always computed from every recorded pick, never from a filtered list.
 */
export type HistResult = "win" | "loss" | "push" | "void" | "pending";

export type HistPick = {
  pick_key: string; date: string; league: string; rank?: number | null; player: string; player_id?: string; team?: string | null;
  home?: string; away?: string; stat: string; selection: "over" | "under"; line: number; projection?: number | null;
  difference?: number | null; model_prob?: number | null; market_prob?: number | null; model_version: string; selected_at?: string;
  game_start?: string; line_source?: string | null; line_captured_at?: string | null; rule?: { min_prob: number; min_edge: number } | null;
  result: HistResult; frozen_before_start?: boolean;
  grade?: { actual?: number | null; played?: boolean; game_status?: string; result_source?: string; graded_at?: string; supersedes?: number; reason?: string } | null;
};
export type HistDay = { date: string; picks: number; reason: string | null };
export type HistFile = {
  generated_at: string; league: string; today: string; picks: HistPick[]; days: HistDay[];
  summary: { unvalidated_until: number }; rule: { min_prob: number; min_edge: number; top_n: number };
  grading: { delay_hours: number; source: string | null };
};

export type Record = { win: number; loss: number; push: number; void: number; pending: number; settled: number; total: number; winRate: number | null };

export function record(picks: HistPick[]): Record {
  const n = { win: 0, loss: 0, push: 0, void: 0, pending: 0 };
  for (const p of picks) n[(p.result in n ? p.result : "pending") as keyof typeof n]++;
  const settled = n.win + n.loss;
  return { ...n, settled, total: picks.length, winRate: settled ? n.win / settled : null };
}

export type Filters = { result?: HistResult | "all"; from?: string; to?: string; player?: string; stat?: string; version?: string };

export function filterPicks(picks: HistPick[], f: Filters): HistPick[] {
  return picks.filter((p) =>
    (!f.result || f.result === "all" || p.result === f.result) &&
    (!f.from || p.date >= f.from) && (!f.to || p.date <= f.to) &&
    (!f.player || p.player_id === f.player || p.player === f.player) &&
    (!f.stat || p.stat === f.stat) && (!f.version || p.model_version === f.version));
}

export function facets(picks: HistPick[]) {
  const uniq = (xs: string[]) => [...new Set(xs.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  return { players: uniq(picks.map((p) => p.player)), stats: uniq(picks.map((p) => p.stat)), versions: uniq(picks.map((p) => p.model_version)) };
}

/** Every date the record covers (recorded days plus today), newest first. */
export function dayList(f: HistFile): string[] {
  return [...new Set([f.today, ...f.days.map((d) => d.date), ...f.picks.map((p) => p.date)])].sort().reverse();
}

export function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Projected vs actual, from the stored projection and the graded stat only. */
export function projectedVsActual(p: HistPick): { projected: number | null; actual: number | null; missBy: number | null } {
  const actual = p.grade?.actual ?? null;
  const projected = p.projection ?? null;
  const missBy = actual == null ? null : p.selection === "over" ? actual - p.line : p.line - actual;
  return { projected, actual, missBy };
}

export const pctText = (r: number | null) => (r == null ? "—" : `${(r * 100).toFixed(1)}%`);
