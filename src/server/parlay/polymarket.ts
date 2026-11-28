import "server-only";
import type { League } from "@/types/domain";
import type { PolymarketQuote } from "@/lib/parlay/types";
import { MARKET_TYPES, normName, slugCodes, type PmEvent, type PmMarket } from "@/server/markets/polymarketLive";

/**
 * Polymarket US contracts for the Parlay Builder (TEST private view only, Moose 2026-11-27). Pure parsing and EXACT
 * matching; fetching is polymarketLive.fetchEvent (public gateway, no key, 60 s cache in memory). Nothing here is
 * stored: PMUS data "may not be redistributed except as PMUS expressly permits" (participant agreement §I.22).
 *
 * Matching rules (no approximate matches):
 *   player   normalised full name equal to exactly ONE player in that game on Model Room's board, AND the contract's
 *            team is that player's team. Otherwise skipped and counted.
 *   prop     "Player N+ stat": YES = at least N; NO = fewer than N. Equals a sportsbook "over N-0.5" (and its under).
 *            A whole-number sportsbook line (push at N) is NOT the same outcome and is never matched.
 *   spread   "Team covers L" for the leg's team at the leg's line (or, half-point lines only, the other team at -L, NO side)
 *   total    "Over L" at the leg's line (under = NO side, half-point lines only: a whole line can push)
 *   winner   the leg team's own full-game winner contract (never the NO side of the opponent's: NFL games can tie)
 */
export interface PmContract {
  kind: "prop" | "spread" | "total" | "moneyline";
  market?: string;
  line: number | null;
  player?: string;
  team?: string;           // lower-case abbreviation as Polymarket gives it
  bid: number | null;
  ask: number | null;
  fee: number | null;
  status: string;
  updatedAt: string | null;
  title: string;
}

const num = (v: unknown): number | null => {
  const x = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(x) ? x : null;
};
const price = (v: unknown): number | null => {
  const x = num(v);
  return x === null || x <= 0 || x >= 1 ? null : x;
};
const status = (m: PmMarket) => (m.active === false || m.closed ? "closed" : (m.status ?? "").replace("MARKET_STATUS_", "").toLowerCase() || "open");
const GAME: Record<string, "spread" | "total" | "moneyline"> = { spreads: "spread", totals: "total", moneyline: "moneyline" };
const fullGame = (k: string, smt: string) =>
  k === "spread" ? smt.endsWith("full_game_spread") : k === "total" ? smt.endsWith("full_game_total") && !smt.includes("team_points") : smt === "moneyline" || smt.endsWith("full_game_winner");

export function contractsOf(ev: PmEvent): PmContract[] {
  const teams = new Map((ev.teams ?? []).map((t) => [t.id, (t.abbreviation ?? "").toLowerCase()]));
  const out: PmContract[] = [];
  for (const m of ev.markets ?? []) {
    const base = { bid: price(m.bestBidQuote?.value), ask: price(m.bestAskQuote?.value), fee: num(m.feeCoefficient), status: status(m), updatedAt: m.updatedAt ?? null };
    const market = MARKET_TYPES[m.sportsMarketType ?? ""];
    if (market) {
      const line = num(m.line);
      const player = m.metadata?.playerName;
      const team = teams.get(m.metadata?.teamId);
      if (line === null || !player || !team) continue;
      out.push({ kind: "prop", market, line, player, team, ...base, title: `${player} ${line}+` });
      continue;
    }
    const k = GAME[m.marketType ?? ""];
    if (!k || !fullGame(k, m.sportsMarketType ?? "")) continue;
    const long = (m.marketSides ?? []).find((s) => s.long);
    if (!long) continue;
    if (k === "total") {
      const line = num(m.line);
      if (line === null || !(long.description ?? "").toLowerCase().startsWith("over")) continue;
      out.push({ kind: "total", line, ...base, title: `Over ${line}` });
    } else {
      const team = (long.team?.abbreviation ?? "").toLowerCase();
      if (!team) continue;
      const line = k === "spread" ? num(m.line) : null;
      if (k === "spread" && line === null) continue;
      out.push({ kind: k, line, team, ...base, title: k === "spread" ? `${team.toUpperCase()} ${line! > 0 ? "+" : ""}${line}` : `${team.toUpperCase()} to win` });
    }
  }
  return out;
}

/** Quote for one side of a yes/no contract. implied = mid of a two-sided, open, uncrossed book; otherwise null. */
export function sideQuote(c: PmContract, yes: boolean, fetchedAt: string, label: string): PolymarketQuote {
  const bid = yes ? c.bid : c.ask === null ? null : 1 - c.ask;
  const ask = yes ? c.ask : c.bid === null ? null : 1 - c.bid;
  const ok = bid !== null && ask !== null && bid <= ask + 1e-9 && c.status === "open";
  const r4 = (x: number) => Math.round(x * 10000) / 10000;
  return { contract: label, bid: bid === null ? null : r4(bid), ask: ask === null ? null : r4(ask), implied: ok ? r4((bid! + ask!) / 2) : null,
    spread: ok ? r4(ask! - bid!) : null, fee: c.fee, status: c.status, updatedAt: c.updatedAt, fetchedAt, liquidity: null };
}

export interface PlayerRef { playerId: string; name: string; team: string }
export interface PropMatch { byPlayerMarket: Map<string, Map<number, PmContract>>; skipped: { ambiguous: number; teamMismatch: number; notOnBoard: number }; matched: number }

/** Exact player matching (see the rules above). Key: `${playerId}|${market}` → line → contract. */
export function matchProps(league: League, contracts: PmContract[], players: PlayerRef[]): PropMatch {
  const byName = new Map<string, PlayerRef[]>();
  for (const p of players) {
    const k = normName(p.name);
    byName.set(k, [...(byName.get(k) ?? []), p]);
  }
  const out = new Map<string, Map<number, PmContract>>();
  const skipped = { ambiguous: 0, teamMismatch: 0, notOnBoard: 0 };
  let matched = 0;
  for (const c of contracts) {
    if (c.kind !== "prop") continue;
    const cands = byName.get(normName(c.player!)) ?? [];
    if (!cands.length) { skipped.notOnBoard++; continue; }
    if (cands.length > 1) { skipped.ambiguous++; continue; }
    const p = cands[0];
    if (!slugCodes(league, p.team).includes(c.team!)) { skipped.teamMismatch++; continue; }
    const k = `${p.playerId}|${c.market}`;
    const m = out.get(k) ?? new Map<number, PmContract>();
    m.set(c.line!, c);
    out.set(k, m);
    matched++;
  }
  return { byPlayerMarket: out, skipped, matched };
}

/** The contract for a game-line leg, and which side of it. null = no exact match. */
export function gameContract(league: League, contracts: PmContract[], kind: "spread" | "total" | "moneyline", teamAbbr: string | null, otherAbbr: string | null,
  line: number | null, over: boolean): { c: PmContract; yes: boolean } | null {
  const isTeam = (c: PmContract, abbr: string | null) => Boolean(abbr && c.team && slugCodes(league, abbr).includes(c.team));
  const eq = (a: number | null, b: number | null) => a !== null && b !== null && Math.abs(a - b) < 1e-9;
  // The NO side only equals the opposite outcome when there's no push or tie: half-point lines. Moneylines use the
  // leg team's own contract only (an NFL tie would make "the other team doesn't win" a different outcome).
  const half = line !== null && Math.abs(Math.abs(line % 1) - 0.5) < 1e-9;
  for (const c of contracts) {
    if (c.kind !== kind) continue;
    if (kind === "total" && eq(c.line, line) && (over || half)) return { c, yes: over };
    if (kind === "moneyline" && isTeam(c, teamAbbr)) return { c, yes: true };
    if (kind === "spread") {
      if (isTeam(c, teamAbbr) && eq(c.line, line)) return { c, yes: true };
      if (half && isTeam(c, otherAbbr) && line !== null && eq(c.line, -line)) return { c, yes: false };
    }
  }
  return null;
}
