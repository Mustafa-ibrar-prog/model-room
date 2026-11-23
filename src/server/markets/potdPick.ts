import type { EnginePropMarket, EnginePropPlayer, EnginePropsBoard } from "@/types/props";

/**
 * NBA Pick of the Day (TEST): the most reliable qualifying NBA player prop against live Polymarket US prices.
 * NBA only (Moose, 2026-11-22). The bar is unchanged (modeling/modelroom/potd.py): at least 56.5% and a 4-point edge
 * after fees, but both are measured with the RELIABILITY-ADJUSTED probability below, and candidates are ranked by it,
 * never by the size of the gap.
 */
export const MIN_PROB = 0.565;
export const MIN_EDGE = 0.04;
export const ELIGIBLE = ["points", "rebounds", "assists", "threes"] as const;
/** Board contribution key for each eligible market. */
export const STAT_KEY: Record<string, string> = { points: "pts", rebounds: "reb", assists: "ast", threes: "fg3m" };

/**
 * Reliability adjustment, fitted on 2023-24 candidate sides of active model 0.2.0 only, tested on 2024-25 and 2025-26
 * (research Phase 8b, p8/rel2.py): logit(p_adj) = a + b*logit(p) + c*toward, where toward = the share of the projection
 * that blowout + matchup + usage adjustments add in the pick's direction (clipped to +/-0.5).
 * Held out: log loss -0.0040 [-0.0050, -0.0032], Brier -0.0016, both seasons better; adjusted probabilities land within
 * about 1 point of actual hit rates in every band from 56.5% to 80% (raw model sides ran 1-5 points overconfident).
 * Fitted for 0.2.0: another model version needs its own fit before it can be used here.
 */
export const RELIABILITY = { intercept: 0.0566, logitP: 0.7479, toward: -2.1913, model: "0.2.0", id: "potd-reliability-1" } as const;
// Applied only at main lines (the contract priced closest to 50¢), the rung it was fitted and tested on.

export interface Factor { key: string; text: string; delta: number | null; favors: "pick" | "against" | "neutral" }

export interface LivePropPick {
  gameId: string; player: string; team: string; opp: string; position: string; matchup: string; start: string | null; stat: string; label: string;
  /** Polymarket "at least N" contract: Yes = over N - 0.5, No = under N - 0.5 */
  contract: number; side: "over" | "under"; line: number;
  /** ask price of the chosen side, its trading fee, and price + fee (the cost the edge is measured against) */
  price: number; fee: number; cost: number;
  /** calibrated model probability of the side, and the reliability-adjusted probability used to qualify and rank */
  modelProb: number; adjProb: number; marketProb: number;
  /** adjusted probability minus cost (after fees) */
  edge: number; rawEdge: number;
  /** unrounded model mean (display rounds it to a whole number) */
  projection: number; difference: number; toward: number;
  modelVersion: string; boardAt: string | null; factors: Factor[];
  minutes: { projected: number | null; usual: number | null };
  form: { seasonAvg: number | null; seasonGames: number | null; last5: number | null };
  support: string;
  /** how often he reached the contract (N+) in box scores: this season and last, null when too few games to say */
  history: { thisSeason: { hits: number; games: number } | null; lastSeason: { hits: number; games: number } | null };
  /** filled by potdLive from the game board and the injury report; null when unavailable */
  game?: GameContext | null; injuries?: InjuryContext | null;
}

/** Box-score game logs published by `python -m modelroom potd` (nba_player_logs.json): player -> season -> stat -> values. */
export interface PlayerLogs { seasons: number[]; players: Record<string, Record<string, Record<string, number[]>>> }
/** Game model context (projected score and margin chances). Shown for context; in model 0.2.0 only the projected
 *  margin feeds the player projection (through the blowout cut, listed among the factors). */
export interface GameContext {
  model: string; home: string; away: string; homeScore: number; awayScore: number; margin: number; total: number; pace: number | null;
  sigma: number; favored: string; p10: number; p15: number; p20: number;
}
/** Official / ESPN injury report entries for both teams (context: model 0.2.0 does not read the report). */
export interface InjuryContext { source: string; reportTime: string | null; team: { name: string; status: string }[]; opp: { name: string; status: string }[] }

function erf(x: number): number {   // Abramowitz-Stegun 7.1.26
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
const ncdf = (z: number) => 0.5 * (1 + erf(z / Math.SQRT2));
/** P(|final margin| >= k) with margin ~ Normal(projected margin, the game model's out-of-sample error SD). */
export function marginChance(margin: number, sigma: number, k: number): number {
  return 1 - ncdf((k - margin) / sigma) + ncdf((-k - margin) / sigma);
}
export function gameContext(g: { home: { abbr: string }; away: { abbr: string }; projection: { home_score: number; away_score: number; margin: number; total: number; pace?: number | null } },
  sigma: number, model: string): GameContext {
  const pr = g.projection;
  return { model, home: g.home.abbr, away: g.away.abbr, homeScore: pr.home_score, awayScore: pr.away_score, margin: pr.margin, total: pr.total,
    pace: pr.pace ?? null, sigma, favored: pr.margin >= 0 ? g.home.abbr : g.away.abbr,
    p10: marginChance(pr.margin, sigma, 10), p15: marginChance(pr.margin, sigma, 15), p20: marginChance(pr.margin, sigma, 20) };
}

export const MIN_GAMES_THIS_SEASON = 5;
export const MIN_GAMES_LAST_SEASON = 20;

export function hitHistory(logs: PlayerLogs | null | undefined, playerId: string, stat: string, contract: number): LivePropPick["history"] {
  const none = { thisSeason: null, lastSeason: null };
  if (!logs || logs.seasons.length < 2) return none;
  const [prev, cur] = logs.seasons.map(String);
  const p = logs.players[playerId];
  if (!p) return none;
  const count = (season: string, min: number) => {
    const v = p[season]?.[stat];
    return v && v.length >= min ? { hits: v.filter((x) => x >= contract).length, games: v.length } : null;
  };
  return { thisSeason: count(cur, MIN_GAMES_THIS_SEASON), lastSeason: count(prev, MIN_GAMES_LAST_SEASON) };
}

/** The contract whose price sits closest to 50 cents: that market's own line for the player and stat. */
export function priceCenter(q: { yes_ask: number | null; no_ask: number | null; mid?: number | null }): number | null {
  if (typeof q.mid === "number") return q.mid;
  if (q.yes_ask != null && q.no_ask != null) return (q.yes_ask + (1 - q.no_ask)) / 2;
  return q.yes_ask ?? (q.no_ask != null ? 1 - q.no_ask : null);
}

export interface Rejected { player: string; team: string; label: string; side: "over" | "under"; line: number; adjProb: number; modelProb: number; edge: number; why: string }

/** Polymarket US trading fee per contract: θ·p·(1−p). */
export const pmFee = (theta: number, price: number) => theta * price * (1 - price);

/** True when line N sits inside the model's own probability grid, so P(stat >= N) is the model's number, not a clamp. */
export function inGrid(grid: { k0: number; step: number; p: number[] } | undefined, n: number): boolean {
  if (!grid || !grid.p.length) return false;
  const x = (n - grid.k0) / grid.step;
  return x >= 0 && x <= grid.p.length - 1 && Math.abs(x - Math.round(x)) < 1e-9;
}

const PT_DAY = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });

/** Games on the board that start later today (Pacific). */
export function todaysGameIds(board: EnginePropsBoard, now: Date): Set<string> {
  const today = PT_DAY(now);
  return new Set(board.games.filter((g) => g.start_time && Date.parse(g.start_time) > now.getTime() && PT_DAY(new Date(g.start_time)) === today).map((g) => g.game_id));
}

type Contribs = Record<string, number>;
function contribs(p: EnginePropPlayer, stat: string): Contribs | null {
  const c = (p.inputs?.contributions as { stats?: Record<string, Contribs> } | undefined)?.stats?.[STAT_KEY[stat]];
  return c && typeof c.baseline === "number" ? c : null;
}

/** Share of the projection added by blowout + matchup + usage in the pick's direction (0 when unknown). */
export function towardShare(c: Contribs | null, side: "over" | "under"): number {
  if (!c || !(c.baseline > 0)) return 0;
  const adj = (c.blowout ?? 0) + (c.matchup ?? 0) + (c.usage ?? 0);
  const t = (side === "over" ? adj : -adj) / c.baseline;
  return Math.max(-0.5, Math.min(0.5, t));
}

export function adjustedProb(p: number, toward: number): number {
  const q = Math.min(Math.max(p, 1e-4), 1 - 1e-4);
  const z = RELIABILITY.intercept + RELIABILITY.logitP * Math.log(q / (1 - q)) + RELIABILITY.toward * toward;
  return 1 / (1 + Math.exp(-z));
}

const r3 = (x: number) => Math.round(x * 1000) / 1000;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The model's own reasons, from the board's contribution breakdown (what actually moved the number). */
export function factorsFor(p: EnginePropPlayer, m: EnginePropMarket, stat: string, side: "over" | "under"): Factor[] {
  const c = contribs(p, stat);
  const out: Factor[] = [];
  const fav = (d: number): Factor["favors"] => (Math.abs(d) < 0.5 ? "neutral" : (d > 0) === (side === "over") ? "pick" : "against");
  const w = (d: number) => (Math.abs(d) < 0.5 ? "barely moves it" : `${d > 0 ? "+" : "−"}${Math.round(Math.abs(d))}`);
  const lbl = m.label.toLowerCase();
  const inp = p.inputs ?? {};
  if (c) {
    const oppF = stat === "threes" ? null : num(inp[`opp_${stat}_factor`]);   // the board publishes points/rebounds/assists factors
    out.push({ key: "matchup", delta: c.matchup ?? 0, favors: fav(c.matchup ?? 0),
      text: `Matchup: ${p.opp} ${oppF == null ? "defense" : oppF > 1.005 ? "allows more" : oppF < 0.995 ? "allows less" : "is about average"} ${oppF == null ? "" : `to ${p.position === "C" ? "centers" : p.position === "F" ? "forwards" : "guards"} `}(${w(c.matchup ?? 0)} ${lbl}).` });
    const mn = (inp.contributions as { minutes?: { usual?: number; projected?: number } } | undefined)?.minutes;
    out.push({ key: "minutes", delta: c.minutes ?? 0, favors: fav(c.minutes ?? 0),
      text: `Minutes: ${mn?.projected != null ? `${Math.round(mn.projected)} projected` : "projected"}${mn?.usual != null ? ` vs ${Math.round(mn.usual)} usual` : ""} (${w(c.minutes ?? 0)}).` });
    if (Math.abs(c.blowout ?? 0) >= 0.05) out.push({ key: "blowout", delta: c.blowout, favors: fav(c.blowout), text: `Blowout risk trims his minutes (${w(c.blowout)} ${lbl}).` });
    const tm = typeof inp.teammates_out === "string" && inp.teammates_out ? inp.teammates_out : null;
    if (tm || Math.abs(c.usage ?? 0) >= 0.05) out.push({ key: "usage", delta: c.usage ?? 0, favors: fav(c.usage ?? 0), text: `Teammates out${tm ? `: ${tm}` : ""} (${w(c.usage ?? 0)} ${lbl} from the extra usage).` });
    if (Math.abs(c.pace ?? 0) >= 0.05) out.push({ key: "pace", delta: c.pace, favors: fav(c.pace), text: `Pace: ${c.pace > 0 ? "faster" : "slower"} game than usual (${w(c.pace)}).` });
  }
  out.push({ key: "injury", delta: null, favors: "neutral",
    text: p.injury_status ? `Listed ${p.injury_status}.` : "Not listed as out. Model 0.2.0 has no injury feed: a player counts as out only after missing 2 straight games." });
  return out;
}

/** Why quotes were dropped, in the order the filters run. */
export interface LiveDiag {
  /** contracts matched, player-stats with at least one, contracts set aside because another rung is the main line */
  quotes: number; lines: number; offMain: number;
  unusable: number; outsideGrid: number; noFee: number; belowProb: number; belowEdge: number; checked: number;
}

/**
 * Every qualifying NBA prop at a MAIN LINE (2026-11-22; several a day allowed, Moose 2026-11-22), most reliable first. Each player and stat is judged only at its
 * Polymarket contract priced closest to 50¢ (the market's own line); other ladder rungs never compete, because the
 * reliability adjustment and every backtest cover main lines only, and shopping deep-tail rungs turns small projection
 * errors into apparent edges. At that contract: usable quote, inside the model's grid, published fee, and the side whose
 * reliability-adjusted probability clears 56.5% with a 4-point edge after fees; ranked by adjusted probability (then
 * edge). Never estimates a line or a price. Also returns the closest rejected main lines and why.
 */
export function strongestLiveProp(board: EnginePropsBoard, ids: Set<string>, logs?: PlayerLogs | null): { pick: LivePropPick | null; picks: LivePropPick[]; checked: number; diag: LiveDiag; rejected: Rejected[] } {
  const picks: LivePropPick[] = [];
  const rej: Rejected[] = [];
  const d: LiveDiag = { quotes: 0, lines: 0, offMain: 0, unusable: 0, outsideGrid: 0, noFee: 0, belowProb: 0, belowEdge: 0, checked: 0 };
  const boardAt = (board as unknown as { generated_at?: string }).generated_at ?? null;
  for (const g of board.games) {
    if (!ids.has(g.game_id)) continue;
    for (const p of g.players) {
      for (const stat of ELIGIBLE) {
        const m = p.markets[stat];
        if (!m) continue;
        const rungs = m.thresholds.filter((t) => t.op === ">=" && !t.variant && t.quotes.some((v) => v.provider === "polymarket_us"));
        if (!rungs.length) continue;
        d.quotes += rungs.length;
        d.lines++;
        // main line: among rungs with a usable quote, the price closest to 50 cents
        let t: (typeof rungs)[number] | null = null;
        let q: (typeof rungs)[number]["quotes"][number] | null = null;
        let gap = Infinity;
        for (const r of rungs) {
          const u = r.quotes.find((v) => v.provider === "polymarket_us" && v.usable);
          const c = u ? priceCenter(u) : null;
          if (u && c != null && Math.abs(c - 0.5) < gap) { gap = Math.abs(c - 0.5); t = r; q = u; }
        }
        if (!t || !q) { d.unusable++; continue; }                          // no tradable rung for this player-stat
        d.offMain += rungs.length - 1;
        if (!inGrid(m.grid, t.threshold)) { d.outsideGrid++; continue; }   // never clamped or estimated
        if (q.fee_coef == null) { d.noFee++; continue; }                  // fee unknown: never assumed free
        d.checked++;
        const c = contribs(p, stat);
        const sides: ["over" | "under", number, number | null][] = [["over", t.model_prob, q.yes_ask], ["under", 1 - t.model_prob, q.no_ask]];
        let probOk = false, edgeOk = false;
        let near: Rejected | null = null;
        for (const [side, prob, price] of sides) {
          if (price === null) continue;
          const toward = towardShare(c, side);
          const adj = adjustedProb(prob, toward);
          const fee = pmFee(q.fee_coef, price);
          const cost = price + fee;
          const edge = adj - cost;
          const line = t.threshold - 0.5;
          const base = { player: p.name, team: p.team, label: m.label, side, line, adjProb: r3(adj), modelProb: r3(prob), edge: r3(edge) };
          if (adj < MIN_PROB) {
            if (prob >= MIN_PROB && (!near || adj > near.adjProb)) near = { ...base, why: `model ${Math.round(prob * 100)}%, but only ${(adj * 100).toFixed(1)}% after the reliability adjustment${toward > 0.05 ? ` (${Math.round(toward * 100)}% of the projection comes from adjustments)` : ""}` };
            continue;
          }
          probOk = true;
          if (edge < MIN_EDGE) {
            if (!near || adj > near.adjProb) near = { ...base, why: `${(edge * 100).toFixed(1)}-point edge after fees at ${(price * 100).toFixed(0)}¢ (needs ${(MIN_EDGE * 100).toFixed(0)})` };
            continue;
          }
          edgeOk = true;
          const sea = p.recent?.season ?? null;
          const vals = (p.recent?.values?.[stat] ?? []).slice(0, 5).filter((v): v is number => typeof v === "number");
          const mn = (p.inputs?.contributions as { minutes?: { usual?: number; projected?: number } } | undefined)?.minutes;
          picks.push({
            gameId: g.game_id, player: p.name, team: p.team, opp: p.opp, position: p.position, matchup: `${g.away.abbr} @ ${g.home.abbr}`, start: g.start_time, stat, label: m.label,
            contract: t.threshold, side, line, price, fee: r3(fee), cost: r3(cost), modelProb: r3(prob), adjProb: r3(adj), marketProb: price,
            edge: r3(edge), rawEdge: r3(prob - cost), projection: m.mean, difference: m.mean - line, toward: r3(toward),
            modelVersion: board.model.version, boardAt, factors: factorsFor(p, m, stat, side),
            minutes: { projected: num(mn?.projected) ?? num(p.inputs?.projected_minutes), usual: num(mn?.usual) },
            form: { seasonAvg: sea ? num(sea.avg?.[stat]) : null, seasonGames: sea ? sea.games : null, last5: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null },
            support: m.support_note, history: hitHistory(logs, p.player_id, stat, t.threshold),
          });
        }
        if (!probOk) d.belowProb++;
        else if (!edgeOk) d.belowEdge++;
        if (near && !edgeOk) rej.push(near);
      }
    }
  }
  rej.sort((a, b) => b.adjProb - a.adjProb || b.edge - a.edge);
  // Every qualifying main line (at most one side per player-stat), most reliable first; no fixed count, none forced.
  picks.sort((a, b) => b.adjProb - a.adjProb || b.edge - a.edge);
  return { pick: picks[0] ?? null, picks, checked: d.checked, diag: d, rejected: rej.slice(0, 3) };
}

/** Plain-language reason for "no qualifying pick", from the fetch counts and the filter counts. */
export function liveReason(info: { games: number; found: number; matched: number; errors?: number; errorCodes?: number[] }, d: LiveDiag): string {
  if (!info.games) return "No NBA games left today.";
  if (info.errors && !info.found) {
    const how = (info.errorCodes ?? []).map((c) => (c ? `HTTP ${c}` : "timeout")).join(", ");
    return `Polymarket didn't answer for ${info.errors} of ${info.games} games (${how}); nothing to compare yet.`;
  }
  if (!info.found) return `Polymarket has no market listed for any of today's ${info.games} games yet.`;
  if (!info.matched || !d.quotes) return `Polymarket lists ${info.found} of ${info.games} games, but no player-prop line matched a player and stat on the model's board.`;
  const parts = [`${d.lines} player-stat main lines checked (${d.quotes} Polymarket contracts matched; ${d.offMain} other ladder rungs set aside)`];
  if (d.unusable) parts.push(`${d.unusable} with no tradable contract now (closed, one-sided or spread too wide)`);
  if (d.outsideGrid) parts.push(`${d.outsideGrid} outside the model's range`);
  if (d.noFee) parts.push(`${d.noFee} without a published fee`);
  if (d.belowProb) parts.push(`${d.belowProb} where neither side reaches ${(MIN_PROB * 100).toFixed(1)}% after the reliability adjustment`);
  if (d.belowEdge) parts.push(`${d.belowEdge} under a ${(MIN_EDGE * 100).toFixed(0)}-point edge after fees`);
  return parts.join("; ") + ".";
}
