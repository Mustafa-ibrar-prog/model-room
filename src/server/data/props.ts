import "server-only";
import { canAccess, gate } from "@/lib/entitlements";
import { loadPropsBoard } from "@/server/engine/board";
import type { League, TierId } from "@/types/domain";
import type { EnginePropPlayer, EnginePropsBoard, EngineThreshold, PropGameView, PropLineView, PropPlayerView, PropsBoard } from "@/types/props";

/**
 * Player props. Plans without "props.projections" get no player data at all: the game count and the
 * model's backtest record only. Model inputs (shares, coverage and blitz factors) need "props.advanced".
 */

function lineView(t: EngineThreshold): PropLineView {
  const usable = t.quotes.filter((q) => q.usable);
  const shown = usable.length ? [...usable].sort((a, b) => (a.spread ?? 1) - (b.spread ?? 1))[0] : null;
  const side = t.best?.edge ?? null;
  const pick = side ? t.best?.[side] : null;
  return {
    op: t.op,
    threshold: t.threshold,
    variant: t.variant,
    modelProb: t.model_prob,
    market: shown
      ? {
          provider: shown.provider,
          mid: shown.mid,
          bid: shown.yes_bid,
          ask: shown.yes_ask,
          spread: shown.spread,
          askSize: shown.ask_size,
          capturedAt: shown.captured_at,
          evYes: shown.ev_yes,
          evNo: shown.ev_no,
        }
      : null,
    quotes: t.quotes.map((q) => ({ provider: q.provider, mid: q.mid, bid: q.yes_bid, ask: q.yes_ask, usable: q.usable, flags: q.flags, capturedAt: q.captured_at })),
    edge:
      side && pick && pick.ev !== null && t.edge_grade?.grade
        ? { side, provider: pick.provider, price: pick.price, ev: pick.ev, grade: t.edge_grade.grade, reasons: t.edge_grade.reasons }
        : null,
  };
}

function playerView(p: EnginePropPlayer, tier: TierId): PropPlayerView {
  return {
    id: p.player_id,
    name: p.name,
    team: p.team,
    opp: p.opp,
    position: p.position,
    injuryStatus: p.injury_status,
    markets: Object.entries(p.markets).map(([key, m]) => ({
      key,
      label: m.label,
      mean: m.mean,
      median: m.median,
      sd: m.sd,
      support: m.support,
      supportNote: m.support_note,
      range80: m.range_80,
      lines: m.thresholds.map(lineView),
    })),
    inputs: gate(tier, "props.advanced", p.inputs),
  };
}

function selected(b: EnginePropsBoard, gameId: string | undefined, tier: TierId): PropGameView | null {
  const g = b.games.find((x) => x.game_id === gameId) ?? b.games[0];
  if (!g) return null;
  return { id: g.game_id, startTime: g.start_time, home: g.home, away: g.away, players: g.players.map((p) => playerView(p, tier)) };
}

export async function getProps(league: League, tier: TierId, gameId?: string): Promise<PropsBoard> {
  const res = await loadPropsBoard(league);
  if (!res.ok) return { ok: false, reason: res.reason };
  const b = res.board;
  const allowed = canAccess(tier, "props.projections");
  return {
    ok: true,
    generatedAt: b.generated_at,
    week: b.week,
    model: { version: b.model.version, status: b.model.status, sims: b.model.sims },
    markets: b.data.markets,
    marketsNotPublished: b.data.markets_not_published,
    rules: b.data.comparison_rules,
    backtest: b.performance.backtest,
    gameCount: b.games.length,
    schedule: b.games.map((g) => ({ id: g.game_id, startTime: g.start_time, home: g.home.abbr, away: g.away.abbr, players: allowed ? g.players.length : 0 })),
    game: allowed ? selected(b, gameId, tier) : gate(tier, "props.projections", null),
  };
}
