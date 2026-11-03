import "server-only";
import { canAccess, gate } from "@/lib/entitlements";
import { loadMarketResultsFile } from "@/server/engine/board";
import type { Gate, League, TierId } from "@/types/domain";
import type { MarketResult, MarketResultsFile, ResultBlock } from "@/types/marketResults";

/**
 * Predictions graded on official exchange settlement. Summaries are open to every plan (it's how the model
 * is judged); the individual records, with the prices seen, are history, which is Pro.
 * Nothing is recomputed from box scores: statuses come from the file the settlement job wrote.
 */
export interface ResultsQuery {
  from?: string;
  to?: string;
  provider?: string;
  market?: string;
  status?: string;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function block(rs: MarketResult[]): ResultBlock {
  const won = rs.filter((r) => r.status === "won").length;
  const lost = rs.filter((r) => r.status === "lost").length;
  const out: ResultBlock = {
    predictions: rs.length,
    settled: rs.filter((r) => r.status !== "pending").length,
    won,
    lost,
    void: rs.filter((r) => r.status === "void").length,
    pending: rs.filter((r) => r.status === "pending").length,
    win_pct: won + lost ? won / (won + lost) : null,
  };
  const g = rs.filter((r) => r.settlement?.state === "settled" && (r.settlement.result === "yes" || r.settlement.result === "no"));
  if (g.length) {
    const clip = (p: number) => Math.min(1 - 1e-4, Math.max(1e-4, p));
    const y = g.map((r) => (r.settlement!.result === "yes" ? 1 : 0));
    const score = (ps: number[], ys: number[]) => ({
      brier: ps.reduce((s, p, i) => s + (p - ys[i]) ** 2, 0) / ps.length,
      log_loss: -ps.reduce((s, p, i) => s + (ys[i] * Math.log(clip(p)) + (1 - ys[i]) * Math.log(1 - clip(p))), 0) / ps.length,
    });
    const m = score(g.map((r) => r.model_prob), y);
    out.n_scored = g.length;
    out.brier = m.brier;
    out.log_loss = m.log_loss;
    const withMkt = g.map((r, i) => [r.market_implied, y[i]] as const).filter(([p]) => p !== null) as [number, number][];
    if (withMkt.length) out.market = { n: withMkt.length, ...score(withMkt.map(([p]) => p), withMkt.map(([, v]) => v)) };
  }
  return out;
}

function calibration(rs: MarketResult[]) {
  const g = rs.filter((r) => r.settlement?.state === "settled" && (r.settlement.result === "yes" || r.settlement.result === "no"));
  const bins = [];
  for (let i = 0; i < 10; i++) {
    const lo = i / 10;
    const hi = (i + 1) / 10;
    const b = g.filter((r) => r.model_prob >= lo && (r.model_prob < hi || (i === 9 && r.model_prob <= 1)));
    if (b.length) {
      bins.push({
        bin: `${lo.toFixed(1)}-${hi.toFixed(1)}`,
        n: b.length,
        predicted: b.reduce((s, r) => s + r.model_prob, 0) / b.length,
        actual: b.filter((r) => r.settlement!.result === "yes").length / b.length,
      });
    }
  }
  return bins;
}

function groupBy(rs: MarketResult[], key: (r: MarketResult) => string): Record<string, ResultBlock> {
  const m = new Map<string, MarketResult[]>();
  for (const r of rs) m.set(key(r), [...(m.get(key(r)) ?? []), r]);
  return Object.fromEntries([...m.entries()].sort().map(([k, v]) => [k, block(v)]));
}

export interface MarketResultsView {
  available: boolean;
  generatedAt: string | null;
  note: string | null;
  providers: MarketResultsFile["providers"];
  withheld: Record<string, number>;
  query: ResultsQuery;
  markets: { key: string; label: string }[];
  providerKeys: string[];
  overall: ResultBlock;
  byMarket: Record<string, ResultBlock>;
  byProvider: Record<string, ResultBlock>;
  byMonth: Record<string, ResultBlock>;
  calibration: ReturnType<typeof calibration>;
  records: Gate<MarketResult[]>;
}

export async function getMarketResults(league: League, tier: TierId, q: ResultsQuery = {}): Promise<MarketResultsView> {
  const f = await loadMarketResultsFile<MarketResultsFile>(league);
  const all = f?.records ?? [];
  const query: ResultsQuery = {
    from: q.from && DATE.test(q.from) ? q.from : undefined,
    to: q.to && DATE.test(q.to) ? q.to : undefined,
    provider: q.provider && all.some((r) => r.provider === q.provider) ? q.provider : undefined,
    market: q.market && all.some((r) => r.market === q.market) ? q.market : undefined,
    status: q.status && ["won", "lost", "void", "pending"].includes(q.status) ? q.status : undefined,
  };
  const inRange = all.filter((r) => {
    const d = r.game_date ?? "";
    return (!query.from || d >= query.from) && (!query.to || d <= query.to) && (!query.provider || r.provider === query.provider) && (!query.market || r.market === query.market);
  });
  const listed = query.status ? inRange.filter((r) => r.status === query.status) : inRange;
  return {
    available: Boolean(f),
    generatedAt: f?.generated_at ?? null,
    note: f?.note ?? null,
    providers: f?.providers ?? [],
    withheld: f?.withheld ?? {},
    query,
    markets: [...new Map(all.map((r) => [r.market, r.market_label])).entries()].map(([key, label]) => ({ key, label })),
    providerKeys: [...new Set(all.map((r) => r.provider))],
    overall: block(inRange),
    byMarket: groupBy(inRange, (r) => r.market_label),
    byProvider: groupBy(inRange, (r) => r.provider),
    byMonth: groupBy(inRange.filter((r) => r.game_date), (r) => r.game_date!.slice(0, 7)),
    calibration: calibration(inRange),
    records: canAccess(tier, "history") ? listed.slice(0, 200) : gate(tier, "history", []),
  };
}

/** Records for one date (history pages). Pro only, like the rest of history. */
export async function getMarketResultsForDate(league: League, date: string, tier: TierId): Promise<Gate<MarketResult[]>> {
  if (!canAccess(tier, "history")) return gate(tier, "history", []);
  const f = await loadMarketResultsFile<MarketResultsFile>(league);
  return (f?.records ?? []).filter((r) => r.game_date === date);
}
