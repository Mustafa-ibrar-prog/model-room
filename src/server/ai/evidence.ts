import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { publishedDir, loadBoard, loadPropsBoard } from "@/server/engine/board";
import type { League } from "@/types/domain";
import type { EngineBoard, EngineFlag, EngineGame } from "@/types/engine";
import type { EnginePropPlayer, EnginePropsBoard } from "@/types/props";
import type { LegOption } from "@/lib/parlay/types";
import type { EvidenceItem, LegEvidence } from "@/lib/parlay/evidence";

/**
 * Evidence for one leg (TEST, Moose 2026-11-28). Built here, deterministically, from data Model Room already stores:
 * the published game and prop boards (model output, inputs, injury feed, sportsbook consensus) and
 * evidence_<league>.json (box-score form, splits, defense vs position, NFL wind), each item stamped with its source
 * and as-of time. Gemini only quotes these items; it never sees anything else and never produces a number.
 * What isn't stored is listed under `missing` instead of being guessed.
 */

export interface EvidenceFile {
  league: League;
  generated_at: string;
  results_through: string | null;
  sources: Record<string, string>;
  defense: Record<string, Record<string, Record<string, { allowed: number; rank: number; of: number; league_avg: number; games: number }>>>;
  players: Record<string, {
    games: ({ date: string; opp: string; home: boolean } & Record<string, unknown>)[];
    values: Record<string, (number | null)[]>;
    season_games: number;
    season: Record<string, { avg: number | null; sd: number | null }>;
    splits: ({ home_games: number; away_games: number } & Record<string, { home: number | null; away: number | null } | number>) | null;
    usage: Record<string, { last5: number | null; season: number | null }>;
  }>;
  weather?: Record<string, { roof: string | null; wind_mph?: number | null; forecast_issued?: string | null; source?: string }>;
}

export interface Sources {
  boards: Partial<Record<League, EngineBoard>>;
  props: Partial<Record<League, EnginePropsBoard>>;
  evidence: Partial<Record<League, EvidenceFile>>;
}

const memo = new Map<string, { at: number; v: EvidenceFile | null }>();
export async function loadEvidenceFile(league: League): Promise<EvidenceFile | null> {
  const hit = memo.get(league);
  if (hit && Date.now() - hit.at < 60_000) return hit.v;
  let v: EvidenceFile | null = null;
  try {
    v = JSON.parse(await readFile(path.join(publishedDir(), `evidence_${league}.json`), "utf8")) as EvidenceFile;
  } catch {
    v = null;
  }
  memo.set(league, { at: Date.now(), v });
  return v;
}

export async function loadSources(leagues: League[]): Promise<Sources> {
  const s: Sources = { boards: {}, props: {}, evidence: {} };
  await Promise.all([...new Set(leagues)].map(async (lg) => {
    const [b, p, e] = await Promise.all([loadBoard(lg), loadPropsBoard(lg), loadEvidenceFile(lg)]);
    if (b.ok) s.boards[lg] = b.board;
    if (p.ok) s.props[lg] = p.board;
    if (e) s.evidence[lg] = e;
  }));
  return s;
}

// ------------------------------------------------------------------------------------------------ helpers
const f1 = (x: number | null | undefined) => (x == null || !Number.isFinite(x) ? "?" : (Math.round(x * 10) / 10).toFixed(1));
const pct = (p: number) => `${(p * 100).toFixed(1)}%`;
const ord = (n: number) => { const s = ["th", "st", "nd", "rd"], v = n % 100; return `${n}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`; };
const signed = (x: number) => `${x > 0 ? "+" : ""}${f1(x)}`;

/** board stat keys (contributions) for each NBA market */
const NBA_CONTRIB: Record<string, string> = { points: "pts", rebounds: "reb", assists: "ast", threes: "fg3m", pra: "pra", steals: "stl", blocks: "blk" };
const CONTRIB_LABEL: Record<string, string> = {
  minutes: "minutes", blowout: "blowout risk", usage: "teammates out (usage)", pace: "pace", matchup: "opponent defense", simulation: "simulation",
  game_environment: "game script", opportunity: "opportunity", matchup_share: "coverage / target share", lineup: "lineup changes",
  matchup_efficiency: "opponent efficiency", other: "other",
};
const NFL_GROUP = (pos: string) => (["QB", "RB", "WR", "TE"].includes(pos) ? pos : null);
const NBA_GROUP = (pos: string) => (pos?.[0] === "C" ? "C" : pos?.[0] === "F" ? "F" : pos?.[0] === "G" ? "G" : null);
const GROUP_NAME: Record<string, string> = { G: "guards", F: "forwards", C: "centers", QB: "quarterbacks", RB: "running backs", WR: "wide receivers", TE: "tight ends" };

/** Leg id -> what it is. Threshold K means "K or more" (over) / "under K". */
export function parseLeg(id: string): { league: League; gameId: string; kind: "prop"; playerId: string; market: string; K: number; side: 1 | -1 }
  | { league: League; gameId: string; kind: "spread" | "total" | "moneyline"; side: 1 | -1; line: number | null } | null {
  const p = id.split("~");
  const league = p[0] as League;
  if (league !== "nba" && league !== "nfl") return null;
  if (p[2] === "prop" && p.length === 7) {
    const tag = p[5];
    const n = Number(tag.slice(1));
    if (!Number.isFinite(n)) return null;
    const K = tag[0] === "b" ? n + 0.5 : n;
    return { league, gameId: p[1], kind: "prop", playerId: p[3], market: p[4], K, side: p[6] === "u" ? -1 : 1 };
  }
  if (p[2] === "spread") return { league, gameId: p[1], kind: "spread", side: p[3] === "away" ? -1 : 1, line: Number(p[4]) };
  if (p[2] === "total") return { league, gameId: p[1], kind: "total", side: p[3] === "under" ? -1 : 1, line: Number(p[4]) };
  if (p[2] === "ml") return { league, gameId: p[1], kind: "moneyline", side: p[3] === "away" ? -1 : 1, line: null };
  return null;
}

class Items {
  list: EvidenceItem[] = [];
  missing: string[] = [];
  add(kind: EvidenceItem["kind"], text: string, source: string, asOf: string | null, lean: EvidenceItem["lean"] = "neutral") {
    this.list.push({ id: `E${this.list.length + 1}`, kind, text, source, asOf, lean });
  }
}

// ------------------------------------------------------------------------------------------------ build
export function buildEvidence(legs: LegOption[], src: Sources, now = new Date()): Record<string, LegEvidence> {
  const out: Record<string, LegEvidence> = {};
  for (const leg of legs) {
    const q = parseLeg(leg.id);
    if (!q) continue;
    const it = new Items();
    const board = src.boards[q.league];
    const game = board?.upcoming.find((g) => g.game_id === q.gameId) ?? null;
    if (q.kind === "prop") propEvidence(it, leg, q, src, game, now);
    else gameEvidence(it, leg, q, src, game);
    out[leg.id] = { items: it.list, missing: [...new Set(it.missing)] };
  }
  return out;
}

function propEvidence(it: Items, leg: LegOption, q: { league: League; gameId: string; playerId: string; market: string; K: number; side: 1 | -1 },
  src: Sources, game: EngineGame | null, now: Date) {
  const pb = src.props[q.league];
  const pg = pb?.games.find((g) => g.game_id === q.gameId);
  const pl = pg?.players.find((p) => p.player_id === q.playerId) as EnginePropPlayer | undefined;
  const m = pl?.markets[q.market];
  const ev = src.evidence[q.league];
  const epl = ev?.players[q.playerId];
  const noun = (m?.label ?? q.market).toLowerCase();
  const over = q.side > 0;
  const boardAt = pb?.generated_at ?? null;
  const modelSrc = `Model Room ${q.league.toUpperCase()} props model ${(pb as unknown as { model?: { version?: string } })?.model?.version ?? ""}`.trim();
  if (!pl || !m) {
    it.missing.push("The player's projection isn't on the current board.");
    return;
  }
  const want = (v: number) => (over ? v >= q.K : v < q.K);

  // model reasoning
  it.add("model", `Model projects ${f1(m.mean)} ${noun} (80% range ${f1(m.range_80[0])} to ${f1(m.range_80[1])}); chance of ${over ? `${q.K}+` : `under ${q.K}`}: ${pct(leg.p)}.`, modelSrc, boardAt);
  const inputs = pl.inputs as Record<string, unknown>;
  const con = (inputs.contributions as { stats?: Record<string, Record<string, number>> } | undefined)?.stats;
  const cs = con?.[q.league === "nba" ? NBA_CONTRIB[q.market] ?? "" : q.market];
  if (cs && typeof cs.baseline === "number") {
    const parts = Object.entries(cs).filter(([k, v]) => !["baseline", "final", "simulation"].includes(k) && Math.abs(v) >= Math.max(0.05, Math.abs(cs.baseline) * 0.015))
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 3);
    if (parts.length) {
      it.add("model", `From his baseline of ${f1(cs.baseline)} ${noun}, the model's biggest adjustments: ${parts.map(([k, v]) => `${CONTRIB_LABEL[k] ?? k} ${signed(v)}`).join(", ")}.`,
        modelSrc, boardAt, leanOf(parts.reduce((a, [, v]) => a + v, 0), over));
    }
  }
  if (m.support && m.support !== "ok") it.add("model", `Model flags limited history for this player and stat (${m.support}).`, modelSrc, boardAt, "against");

  // recent form (box scores, not the model)
  const vals = (epl?.values[q.market] ?? pl.recent?.values?.[q.market] ?? []).filter((x): x is number => typeof x === "number");
  const fsrc = ev?.sources.box_scores ?? "box scores";
  const fAt = ev?.results_through ?? null;
  if (vals.length) {
    const span = (n: number) => { const v = vals.slice(0, n); const h = v.filter(want).length; const a = v.reduce((s, x) => s + x, 0) / v.length; return { n: v.length, h, a }; };
    const w = [5, 10, 15].map(span).filter((s, i, arr) => i === 0 || s.n > arr[i - 1].n);
    it.add("form", `Last ${w.map((s) => `${s.n}: ${s.h} of ${s.n} ${over ? `at ${q.K}+` : `under ${q.K}`} (avg ${f1(s.a)})`).join("; ")}. Past games, not the model's chance.`, fsrc, fAt,
      leanOf(w[w.length - 1].a - q.K, over, 0.1 * Math.max(1, q.K)));
    const s5 = w[0], sl = w[w.length - 1];
    if (sl.n >= 8 && Math.abs(s5.h / s5.n - sl.h / sl.n) >= 0.3) {
      it.add("form", `${s5.h / s5.n > sl.h / sl.n ? "Hotter" : "Colder"} lately: ${s5.h} of the last ${s5.n} versus ${sl.h} of the last ${sl.n}.`, fsrc, fAt,
        (s5.h / s5.n > sl.h / sl.n) === true ? "supports" : "against");
    }
  } else it.missing.push("No recent games for this stat.");
  const sea = epl?.season[q.market];
  if (sea?.avg != null && epl) {
    const cv = sea.sd != null && sea.avg > 0 ? sea.sd / sea.avg : null;
    it.add("form", `Season: ${f1(sea.avg)} ${noun} a game over ${epl.season_games} games${sea.sd != null ? `, typical swing ${f1(sea.sd)}` : ""}${cv != null && cv > 0.6 ? " (very up and down)" : cv != null && cv < 0.3 ? " (consistent)" : ""}.`,
      fsrc, fAt, leanOf(sea.avg - q.K, over, 0.1 * Math.max(1, q.K)));
  }
  if (epl && epl.season_games < 15) it.missing.push(`Only ${epl.season_games} games this season, so the last 15 includes everything there is.`);

  // minutes / opportunity
  if (q.league === "nba") {
    const pm = typeof inputs.projected_minutes === "number" ? inputs.projected_minutes : null;
    const mu = epl?.usage.minutes;
    if (pm != null || mu) {
      const trend = mu?.last5 != null && mu?.season != null ? mu.last5 - mu.season : null;
      it.add("usage", `Minutes: model expects ${f1(pm)}; last 5 averaged ${f1(mu?.last5)} against ${f1(mu?.season)} for the season.`, `${modelSrc}; ${fsrc}`, boardAt,
        trend == null ? "neutral" : leanOf(trend, over, 1.5));
    }
    const sh = epl?.usage.fga;
    if (sh?.last5 != null && sh?.season != null && ["points", "pra", "threes"].includes(q.market)) {
      it.add("usage", `Shot attempts: ${f1(sh.last5)} a game over his last 5, ${f1(sh.season)} for the season.`, fsrc, fAt, leanOf(sh.last5 - sh.season, over, 1.5));
    }
  } else {
    const share = typeof inputs.snap_share_recent === "number" ? inputs.snap_share_recent : null;
    const u = epl?.usage;
    const key = ["receptions", "receiving_yards", "longest_reception"].includes(q.market) ? "targets" : ["rushing_yards", "rushing_attempts"].includes(q.market) ? "carries" : q.market.startsWith("passing") || q.market === "interceptions" ? "pass_att" : null;
    if (share != null) it.add("usage", `Recent snap share: ${pct(share)}.`, modelSrc, boardAt);
    if (key && u?.[key]?.last5 != null && u[key].season != null) {
      it.add("usage", `${key === "pass_att" ? "Pass attempts" : key[0].toUpperCase() + key.slice(1)}: ${f1(u[key].last5)} a game over his last 5, ${f1(u[key].season)} for the season.`, fsrc, fAt,
        leanOf(u[key].last5! - u[key].season!, over, 1));
    }
    if (q.market.startsWith("passing") || q.market === "interceptions") {
      const qb = inputs.starting_qb, att = inputs.starting_qb_career_attempts;
      if (typeof qb === "string") it.add("lineup", `Projected starting QB: ${qb}${typeof att === "number" ? ` (${att} career attempts)` : ""}.`, modelSrc, boardAt);
    }
  }

  // matchup: defense vs this position and stat
  const grp = q.league === "nba" ? NBA_GROUP(pl.position) : NFL_GROUP(pl.position);
  const d = grp && ev?.defense[pl.opp]?.[grp]?.[q.market];
  if (d) {
    const helps = d.rank <= Math.round(d.of / 4);
    const hurts = d.rank > d.of - Math.round(d.of / 4);
    it.add("matchup", `${pl.opp} allow ${f1(d.allowed)} ${noun} a game to ${GROUP_NAME[grp!]}, ${ord(d.rank)} most of ${d.of} (league average ${f1(d.league_avg)}, ${d.games} games).`,
      `${fsrc} (Model Room tally)`, fAt, helps ? (over ? "supports" : "against") : hurts ? (over ? "against" : "supports") : "neutral");
  } else it.missing.push("No defense-versus-position figure for this stat and opponent (sample too small or stat not tracked).");
  if (q.league === "nba") {
    const rt = src.boards.nba?.ratings ?? [];
    const opp = rt.find((r) => r.abbr === pl.opp) as (typeof rt[number] & { pace?: number }) | undefined;
    const paces = rt.map((r) => (r as { pace?: number }).pace).filter((x): x is number => typeof x === "number").sort((a, b) => b - a);
    if (opp?.pace != null && paces.length) {
      const rk = paces.indexOf(opp.pace) + 1;
      it.add("matchup", `${pl.opp} play at the ${ord(rk)} fastest pace of ${paces.length} (${f1(opp.pace)} possessions per 48).`, "Model Room team ratings (box scores)", src.boards.nba?.generated_at ?? null,
        rk <= 8 ? (over ? "supports" : "against") : rk > paces.length - 8 ? (over ? "against" : "supports") : "neutral");
    }
  }
  it.missing.push("No defensive scheme or individual matchup data is collected.");

  // injuries and lineup
  const own = pl.injury_status;
  if (own && !/^available$/i.test(own)) it.add("injury", `He is listed ${own.toLowerCase()} on the injury report.`, "injury feed", boardAt, "against");
  if (q.league === "nba") {
    const outs = typeof inputs.teammates_out === "string" ? inputs.teammates_out : null;
    const freed = typeof inputs.usage_freed_by_absences === "number" ? inputs.usage_freed_by_absences : 0;
    if (outs) it.add("injury", `Teammates out: ${outs}.${freed >= 0.005 ? ` The model adds ${pct(freed)} usage for him from their absence.` : " The model doesn't expect it to change his usage."}`,
      "official NBA injury report + ESPN (via the model)", boardAt, freed > 0.02 ? (over ? "supports" : "against") : "neutral");
    const unc = (inputs.uncertain_teammates as { name: string; play_prob: number }[] | undefined) ?? [];
    if (unc.length) it.add("injury", `Uncertain teammates: ${unc.slice(0, 3).map((u) => u.name).join(", ")}.`, "injury feed (via the model)", boardAt);
  } else {
    const det = (inputs.teammates_out_detail as { name: string; position: string; status: string; long_term?: boolean }[] | undefined) ?? [];
    const recent = det.filter((x) => !x.long_term && ["QB", "RB", "WR", "TE", "OL", "T", "G", "C"].includes(x.position)).slice(0, 4);
    if (recent.length) it.add("injury", `Teammates out or doubtful (not long-term): ${recent.map((x) => `${x.name} (${x.position}, ${x.status})`).join(", ")}.`, "ESPN / nflverse injury reports (via the model)", boardAt);
  }
  const oppFlags = game ? flagsFor(game, pl.opp) : [];
  if (oppFlags.length) it.add("injury", `${pl.opp} missing: ${oppFlags.slice(0, 4).map((f) => `${f.player} (${f.position ?? "?"}, ${f.status})`).join(", ")}.`, srcOf(oppFlags), oppFlags[0].report_time);
  it.missing.push("Starting lineups aren't confirmed by any source Model Room collects.");

  // game environment
  if (game) environment(it, game, q.league, pl.team, over, q.market, src.boards[q.league]?.generated_at ?? null);
  // home / away
  const sp = epl?.splits as Record<string, unknown> | null | undefined;
  const sm = sp?.[q.market] as { home: number | null; away: number | null } | undefined;
  const isHome = game ? game.home.abbr === pl.team : null;
  if (sm && isHome != null && sm.home != null && sm.away != null) {
    const here = isHome ? sm.home : sm.away, there = isHome ? sm.away : sm.home;
    it.add("split", `${isHome ? "At home" : "On the road"} he averages ${f1(here)} ${noun} (${isHome ? sp!.home_games : sp!.away_games} games) against ${f1(there)} ${isHome ? "away" : "at home"}.`,
      fsrc, fAt, leanOf(here - q.K, over, 0.1 * Math.max(1, q.K)));
  } else it.missing.push("Home/away split not shown: fewer than 5 games on one side this season.");
  if (q.league === "nfl") weather(it, src, q.gameId, ["passing_yards", "passing_completions", "receiving_yards", "longest_reception", "receptions"].includes(q.market) ? over : null);
  void now;
}

function gameEvidence(it: Items, leg: LegOption, q: { league: League; gameId: string; kind: "spread" | "total" | "moneyline"; side: 1 | -1; line: number | null },
  src: Sources, game: EngineGame | null) {
  const board = src.boards[q.league];
  if (!game || !board) {
    it.missing.push("The game isn't on the current board.");
    return;
  }
  const at = board.generated_at;
  const ms = `Model Room ${q.league.toUpperCase()} game model`;
  const pr = game.projection;
  const team = q.side > 0 ? game.home.abbr : game.away.abbr;
  if (q.kind === "total") {
    it.add("model", `Model projects ${f1(pr.total)} total points${pr.total_range_80 ? ` (80% range ${f1(pr.total_range_80[0])} to ${f1(pr.total_range_80[1])})` : ""}; chance of this leg: ${pct(leg.p)}.`, ms, at);
  } else {
    it.add("model", `Model projects ${game.home.abbr} by ${f1(pr.margin)}${pr.margin_range_80 ? ` (80% range ${f1(pr.margin_range_80[0])} to ${f1(pr.margin_range_80[1])})` : ""}; chance of this leg: ${pct(leg.p)}.`, ms, at);
  }
  const adj = game.adjustments;
  const bits = [adj.rest_points ? `rest ${signed(adj.rest_points)}` : null, adj.injury_points ? `injuries ${signed(adj.injury_points)}` : null, adj.qb_points ? `quarterbacks ${signed(adj.qb_points)}` : null].filter(Boolean);
  if (bits.length) it.add("model", `Model adjustments to the home margin: ${bits.join(", ")} points.`, ms, at);
  const rt = board.ratings ?? [];
  for (const side of [game.home.abbr, game.away.abbr]) {
    const r = rt.find((x) => x.abbr === side) as (typeof rt[number] & { last10_margin?: number | null; avg_margin?: number | null }) | undefined;
    if (r) it.add("matchup", `${side}: rated ${ord(r.rank)} of ${rt.length}, average margin ${signed(r.avg_margin ?? 0)}, last 10 games ${signed(r.last10_margin ?? 0)}.`, "Model Room team ratings", at,
      q.kind === "total" ? "neutral" : side === team ? (r.rank <= rt.length / 3 ? "supports" : r.rank > (2 * rt.length) / 3 ? "against" : "neutral") : "neutral");
  }
  for (const side of [game.home.abbr, game.away.abbr]) {
    const fl = flagsFor(game, side);
    if (fl.length) it.add("injury", `${side} missing: ${fl.slice(0, 4).map((f) => `${f.player} (${f.position ?? "?"}, ${f.status})`).join(", ")}.`, srcOf(fl), fl[0].report_time,
      q.kind === "total" ? "neutral" : side === team ? "against" : "supports");
  }
  if (game.quarterbacks) it.add("lineup", `Projected QBs: ${game.away.abbr} ${game.quarterbacks.away ?? "unknown"}, ${game.home.abbr} ${game.quarterbacks.home ?? "unknown"}.`, ms, at);
  environment(it, game, q.league, null, q.side > 0, null, at);
  it.missing.push("Starting lineups aren't confirmed by any source Model Room collects.");
  if (q.league === "nfl") weather(it, src, q.gameId, q.kind === "total" ? q.side > 0 : null);
}

function environment(it: Items, game: EngineGame, league: League, team: string | null, over: boolean, market: string | null, boardAt: string | null) {
  const mk = game.market;
  if (mk && (mk.spread != null || mk.total != null)) {
    const fav = mk.spread == null ? null : mk.spread < 0 ? game.home.abbr : game.away.abbr;
    it.add("environment", `Sportsbook consensus: ${fav ? `${fav} by ${f1(Math.abs(mk.spread!))}` : "no spread"}${mk.total != null ? `, total ${f1(mk.total)}` : ""} (${mk.books} books).`, (mk.sources ?? []).join(", ") || "sportsbooks", mk.captured_at);
    const big = mk.spread != null && Math.abs(mk.spread) >= (league === "nba" ? 10 : 10);
    if (big && team && market) it.add("environment", `Blowout risk: a ${f1(Math.abs(mk.spread!))}-point spread can cut starters' late minutes.`, "sportsbook spread", mk.captured_at, over ? "against" : "supports");
  } else it.missing.push("No sportsbook spread or total stored for this game.");
  if (league === "nba") {
    const r = game.rest;
    const b2b = [r.home_b2b ? game.home.abbr : null, r.away_b2b ? game.away.abbr : null].filter(Boolean);
    if (b2b.length) it.add("environment", `Back-to-back: ${b2b.join(" and ")}.`, "schedule", boardAt, team && b2b.includes(team) ? (over ? "against" : "supports") : "neutral");
    const pace = (game.projection as unknown as { pace?: number }).pace;
    if (typeof pace === "number") it.add("environment", `Model expects ${f1(pace)} possessions in this game.`, "Model Room NBA game model", boardAt);
  }
}

function weather(it: Items, src: Sources, gameId: string, overPass: boolean | null) {
  const w = src.evidence.nfl?.weather?.[gameId];
  if (!w) {
    it.missing.push("No weather stored for this game.");
    return;
  }
  if (w.roof === "dome" || w.roof === "closed") {
    it.add("weather", "Indoors (dome): weather doesn't apply.", "nflverse schedule", null);
    return;
  }
  if (w.wind_mph != null) {
    const windy = w.wind_mph >= 15;
    it.add("weather", `Wind forecast around kickoff: ${f1(w.wind_mph)} mph${windy ? " (strong enough to affect passing and kicking)" : ""}.`, w.source ?? "NWS GFS MOS", w.forecast_issued ?? null,
      windy && overPass != null ? (overPass ? "against" : "supports") : "neutral");
  } else it.missing.push("No wind forecast stored yet for this game (forecasts start about 40 hours before kickoff).");
  it.missing.push("Temperature and precipitation aren't collected.");
}

function flagsFor(game: EngineGame, team: string): EngineFlag[] {
  const a = game.availability;
  if (!a) return [];
  const side = game.home.abbr === team ? a.home : game.away.abbr === team ? a.away : [];
  return side.filter((f) => (f.status === "out" || f.status === "doubtful") && !f.long_term);
}
const srcOf = (fl: EngineFlag[]) => [...new Set(fl.map((f) => f.source))].join(" + ").replace("nba_official", "official NBA injury report").replace("espn", "ESPN");

/** Direction of a difference for this leg's side: positive x favours an over. */
function leanOf(x: number, over: boolean, dead = 0): EvidenceItem["lean"] {
  if (!Number.isFinite(x) || Math.abs(x) <= dead) return "neutral";
  return (x > 0) === over ? "supports" : "against";
}
