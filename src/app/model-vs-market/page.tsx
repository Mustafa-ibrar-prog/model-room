import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { canAccess } from "@/lib/entitlements";
import { formatKickoff, formatMoneyline, formatPct, formatTimestamp } from "@/lib/format";
import { loadBoard } from "@/server/engine/board";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";
import type { EngineGame, EngineSide } from "@/types/engine";
import { LockedPanel, PageHeader, TableSkeleton, Unavailable } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Model vs market" };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default function ModelVsMarketPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader
        title="Model vs market"
        intro="Every upcoming game line where a market price is on file, next to the model's own probability at that exact line. Fair odds and expected value come from the model's full distribution, with pushes on whole-number lines counted as stake back."
      />
      <Suspense fallback={<div className="mx-auto max-w-7xl px-4 sm:px-6"><TableSkeleton rows={10} /></div>}>
        <Body searchParams={searchParams} />
      </Suspense>
    </>
  );
}

interface Row {
  key: string;
  league: League;
  game: EngineGame;
  market: "Spread" | "Total" | "Moneyline";
  side: string;
  line: number | null;
  modelLine: number | null;
  s: EngineSide;
  book: string;
  capturedAt: string | null;
  version: string;
  generatedAt: string;
}

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
const signed = (x: number) => (x > 0 ? `+${x}` : `${x}`);

function rowsFor(league: League, games: EngineGame[], version: string, generatedAt: string): Row[] {
  const out: Row[] = [];
  for (const g of games) {
    const e = g.edges;
    if (!e) continue;
    const books: [string, NonNullable<EngineGame["edges"]>, string | null][] = e.by_book && Object.keys(e.by_book).length
      ? Object.entries(e.by_book).map(([b, x]) => [b, { ...e, ...x }, x.captured_at])
      : [[(g.market?.sources ?? []).join(", ") || "unknown", e, g.market?.captured_at ?? null]];
    for (const [book, x, cap] of books) {
      const base = { league, game: g, book, capturedAt: cap, version, generatedAt };
      if (x.at_spread) {
        const l = x.at_spread.line;
        out.push({ ...base, key: `${g.game_id}-${book}-sh`, market: "Spread", side: `${g.home.abbr} ${signed(l)}`, line: l, modelLine: g.projection.spread, s: x.at_spread.home });
        out.push({ ...base, key: `${g.game_id}-${book}-sa`, market: "Spread", side: `${g.away.abbr} ${signed(-l)}`, line: -l, modelLine: -g.projection.spread, s: x.at_spread.away });
      }
      if (x.at_total) {
        const l = x.at_total.line;
        out.push({ ...base, key: `${g.game_id}-${book}-to`, market: "Total", side: `Over ${l}`, line: l, modelLine: g.projection.total, s: x.at_total.over });
        out.push({ ...base, key: `${g.game_id}-${book}-tu`, market: "Total", side: `Under ${l}`, line: l, modelLine: g.projection.total, s: x.at_total.under });
      }
      if (x.moneyline) {
        out.push({ ...base, key: `${g.game_id}-${book}-mh`, market: "Moneyline", side: `${g.home.abbr} to win`, line: null, modelLine: null, s: x.moneyline.home });
        out.push({ ...base, key: `${g.game_id}-${book}-ma`, market: "Moneyline", side: `${g.away.abbr} to win`, line: null, modelLine: null, s: x.moneyline.away });
      }
    }
  }
  return out;
}

async function Body({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const viewer = await getViewer();
  if (!canAccess(viewer.tier, "games.edgeFinder.full")) {
    return (
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <LockedPanel requires="plus" title="Model vs market is on Plus" body="It shows the model's probability, fair odds and expected value at every market line on file." />
      </div>
    );
  }
  const lg = one(sp.sport);
  const mk = one(sp.market);
  const sort = one(sp.sort) ?? "ev";
  const leagues: League[] = lg === "nfl" || lg === "nba" ? [lg] : ["nba", "nfl"];
  const boards = await Promise.all(leagues.map(async (l) => ({ l, r: await loadBoard(l) })));
  let rows = boards.flatMap(({ l, r }) => (r.ok ? rowsFor(l, r.board.upcoming, r.board.model.version, r.board.generated_at) : []));
  if (mk) rows = rows.filter((r) => r.market.toLowerCase() === mk);
  const key = (r: Row) => (sort === "diff" ? Math.abs(r.s.model_prob - (r.s.market_implied ?? r.s.model_prob)) : r.s.ev_per_dollar ?? -9);
  rows.sort((a, b) => key(b) - key(a));
  const q = (o: Record<string, string | undefined>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ sport: lg, market: mk, sort, ...o })) if (v) p.set(k, v);
    return `/model-vs-market?${p}`;
  };
  const chip = (on: boolean) => `rounded-full border px-3 py-1 text-sm ${on ? "border-model bg-model/10 text-ink" : "border-navy-700 text-mute hover:text-ink"}`;
  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 pb-16 sm:px-6">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filters">
        {[["", "Both leagues"], ["nba", "NBA"], ["nfl", "NFL"]].map(([v, t]) => <Link key={t} href={q({ sport: v || undefined })} className={chip((lg ?? "") === v)}>{t}</Link>)}
        <span className="w-px bg-navy-700" />
        {[["", "All markets"], ["spread", "Spread"], ["total", "Total"], ["moneyline", "Moneyline"]].map(([v, t]) => <Link key={t} href={q({ market: v || undefined })} className={chip((mk ?? "") === v)}>{t}</Link>)}
        <span className="w-px bg-navy-700" />
        {[["ev", "Sort by EV"], ["diff", "Sort by disagreement"]].map(([v, t]) => <Link key={v} href={q({ sort: v })} className={chip(sort === v)}>{t}</Link>)}
      </div>
      {!rows.length ? (
        <Unavailable title="No market prices on file for upcoming games" body="Sportsbook lines appear here once a market source is connected (The Odds API key on the test site). Nothing is filled in when a line is missing." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-navy-700 bg-navy-900">
          <table className="w-full min-w-[56rem] text-sm">
            <thead className="text-faint">
              <tr className="text-left">
                {["Game", "Market", "Side", "Model line", "Model prob", "Market prob", "Fair odds", "Market odds", "EV per $1", "Source"].map((h) => <th key={h} className="px-3 py-2 font-500">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const ev = r.s.ev_per_dollar;
                return (
                  <tr key={r.key} className="border-t border-navy-700/70">
                    <td className="px-3 py-2"><div className="text-ink">{r.game.away.abbr} @ {r.game.home.abbr}</div><div className="text-xs text-faint">{r.league.toUpperCase()}, {formatKickoff(r.game.start_time)}</div></td>
                    <td className="px-3 py-2">{r.market}</td>
                    <td className="px-3 py-2 text-ink">{r.side}</td>
                    <td className="px-3 py-2 font-mono text-model">{r.modelLine == null ? "–" : r.market === "Spread" ? signed(Number(r.modelLine.toFixed(1))) : r.modelLine.toFixed(1)}</td>
                    <td className="px-3 py-2 font-mono text-model">{formatPct(r.s.model_prob, 1)}{r.s.push_prob > 0.001 ? <span className="text-xs text-faint"> (push {formatPct(r.s.push_prob, 1)})</span> : null}</td>
                    <td className="px-3 py-2 font-mono text-market">{r.s.market_implied == null ? "–" : formatPct(r.s.market_implied, 1)}</td>
                    <td className="px-3 py-2 font-mono text-model">{r.s.fair_odds == null ? "–" : formatMoneyline(r.s.fair_odds)}</td>
                    <td className="px-3 py-2 font-mono text-market">{r.s.market_price == null ? <span className="text-faint">no price</span> : formatMoneyline(r.s.market_price)}</td>
                    <td className={`px-3 py-2 font-mono ${ev == null ? "text-faint" : ev > 0 ? "text-good" : "text-danger"}`}>{ev == null ? "–" : `${ev > 0 ? "+" : ""}${(ev * 100).toFixed(1)}¢`}</td>
                    <td className="px-3 py-2 text-xs text-faint">{r.book}{r.capturedAt ? `, ${formatTimestamp(r.capturedAt)}` : ", time not published"}<div>model {r.version}, run {formatTimestamp(r.generatedAt)}</div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-faint">
        Market prob is the price&apos;s break-even probability, vig included. Positive EV is an estimate from the model&apos;s distribution, not a validated edge: no confidence label is shown until the model&apos;s calibration against market lines is established on the Performance page. Player-prop prices aren&apos;t on file: the free sportsbook feed doesn&apos;t cover props.
      </p>
    </div>
  );
}
