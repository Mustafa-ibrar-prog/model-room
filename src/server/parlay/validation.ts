import "server-only";
import { readFileSync } from "node:fs";
import path from "node:path";
import { publishedDir } from "@/server/engine/board";

/** Backtest summaries for the page (modeling/modelroom/parlay/publish_validation.py → data/published/parlay_validation.json). */
export interface ValidationRow { label: string; parlays: number; hit_rate: number | null; predicted: number | null; predicted_independent: number | null; log_loss_gain: number | null; log_loss_gain_95ci: [number, number] | null }
export interface Validation {
  generated_at: string;
  parlay: ValidationRow[];
  calibration: { bin: [number, number]; n: number; predicted: number; actual: number }[];
  cross_game: { league: string; independent: boolean; max_abs_r: number | null; dependent_cells: number; tested: number }[];
  discovery: { summary: string; top3_roi: number | null; top3_roi_95ci: [number, number] | null; baseline_roi: number | null; picks: number; seasons: number[] } | null;
}

let cached: { at: number; v: Validation | null } | null = null;
export function loadValidation(): Validation | null {
  if (cached && Date.now() - cached.at < 10 * 60_000) return cached.v;
  let v: Validation | null = null;
  try {
    v = JSON.parse(readFileSync(path.join(publishedDir(), "parlay_validation.json"), "utf8")) as Validation;
  } catch {
    v = null;
  }
  cached = { at: Date.now(), v };
  return v;
}
