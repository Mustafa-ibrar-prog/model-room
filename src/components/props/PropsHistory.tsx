import Link from "next/link";
import { formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { longDate } from "@/lib/dates";
import { CATEGORIES } from "@/server/data/explorer";
import { getHistoryDay } from "@/server/data/history";
import { getMarketResultsForDate } from "@/server/data/marketResults";
import { ResultRow, StatusChip } from "@/components/results/SettlementBits";
import type { MarketResult } from "@/types/marketResults";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import { LockedPanel, Unavailable } from "@/components/ui/primitives";

/**
 * A past date in the props explorer: the projections recorded before each game (never re-run), the
 * stat the player actually put up, and Hit/Miss for every threshold the model priced.
 */
export async function PropsHistory({ league, date, game, cat, q }: { league: League; date: string; game?: string; cat?: string; q?: string }) {
  const viewer = await getViewer();
  const [h, settled] = await Promise.all([getHistoryDay(league, date, viewer.tier), getMarketResultsForDate(league, date, viewer.tier)]);
  if (!h.available || !h.games.length) return <Unavailable title={`No ${league.toUpperCase()} games on ${longDate(date)}`} body="Pick another day." />;
  const cats = CATEGORIES[league];
  const category = cats.find((c) => c.key === cat) ?? cats[0];
  const selected = h.games.find((g) => g.game_id === game) ?? h.games[0];
  const link = (patch: Record<string, string | undefined>) => {
    const p = new URLSearchParams({ sport: league, date, game: selected.game_id, cat: category.key, ...(q ? { q } : {}) });
    for (const [k, v] of Object.entries(patch)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    return `/props?${p}`;
  };
  const chip = (on: boolean) =>
    `whitespace-nowrap rounded-md border px-3 py-1.5 text-sm ${on ? "border-model bg-model font-600 text-navy-950" : "border-navy-700 bg-navy-900 text-ink hover:border-navy-600"}`;
  return (
    <div className="space-y-4">
      <nav aria-label="Games" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
        {h.games.map((g) => (
          <Link key={g.game_id} href={link({ game: g.game_id })} className={chip(g.game_id === selected.game_id)}>
            {g.away} @ {g.home}
            {g.final ? <span className="ml-1.5 font-mono text-xs opacity-80">{g.final.away}-{g.final.home}</span> : null}
          </Link>
        ))}
      </nav>
      <nav aria-label="Stat" className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
        {cats.map((c) => (
          <Link key={c.key} href={link({ cat: c.key })} className={chip(c.key === category.key)}>{c.label}</Link>
        ))}
      </nav>
      {isLocked(h.props) ? (
        <LockedPanel requires={h.props.requires} title="Prop results are on Pro" body="Pro shows every projection recorded before the game, the stat each player actually put up, and Hit or Miss on every line." />
      ) : (
        <Rows
          rows={h.props.filter((p) => p.game_id === selected.game_id && p.markets[category.key] && (!q || p.player.toLowerCase().includes(q.toLowerCase())))}
          cat={category.key}
          final={Boolean(selected.final)}
          settled={isLocked(settled) ? [] : settled.filter((r) => r.kind === "prop" && r.game_id === selected.game_id && r.market === category.key)}
        />
      )}
    </div>
  );
}

function Rows({ rows, cat, final, settled }: { rows: import("@/types/history").HistoryProp[]; cat: string; final: boolean; settled: MarketResult[] }) {
  if (!rows.length) {
    return <Unavailable title="Nothing recorded for this game" body="No prop projection was written before this game started, so there's nothing to grade. Prop records begin with the first model run." />;
  }
  const sorted = [...rows].sort((a, b) => b.markets[cat].mean - a.markets[cat].mean);
  const graded = sorted.flatMap((r) => r.markets[cat].thresholds.filter((t) => t.hit !== null));
  const avgP = graded.length ? graded.reduce((s, t) => s + t.p, 0) / graded.length : null;
  const hits = graded.filter((t) => t.hit).length;
  return (
    <div className="space-y-3">
      {graded.length ? (
        <p className="text-sm text-mute">
          {graded.length} lines checked against the box score: {hits} hit ({formatPct(hits / graded.length)}) against an average model probability of
          {" "}{formatPct(avgP!)}. Hit / Miss here is the projection against the actual stat, not a market result; exchange markets are graded only on their
          official settlement, shown under each player.
        </p>
      ) : (
        <p className="text-sm text-mute">{final ? "No graded lines yet: player stats for this game aren't in." : "Results appear once the game is final."}</p>
      )}
      <ul className="divide-y divide-navy-700 rounded-lg border border-navy-700 bg-navy-900">
        {sorted.map((r) => {
          const m = r.markets[cat];
          return (
            <li key={r.player_id} className="space-y-2 px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="font-600 text-ink">{r.player}</span>
                <span className="font-mono text-xs text-faint">{r.team}</span>
                <span className="ml-auto font-mono text-sm text-mute">
                  Projected <span className="text-model">{formatNumber(m.mean)}</span> ± {formatNumber(m.sd)}
                  <span className="mx-2 text-faint">|</span>
                  Actual <span className="text-ink">{r.played === false ? "DNP" : m.actual == null ? "–" : formatNumber(m.actual)}</span>
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {m.thresholds.map((t) => (
                  <span
                    key={t.k}
                    className={`rounded border px-2 py-0.5 font-mono text-xs ${t.hit === null ? "border-navy-700 text-mute" : t.hit ? "border-good/60 text-good" : "border-danger/50 text-danger"}`}
                  >
                    {t.k}+ {formatPct(t.p)} {t.hit === null ? "" : t.hit ? "Hit" : "Miss"}
                  </span>
                ))}
              </div>
              {settled.some((s) => s.player_id === r.player_id) ? (
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-1.5 text-[0.68rem] text-faint">
                    Exchange markets:{" "}
                    {settled.filter((s) => s.player_id === r.player_id).map((s) => <StatusChip key={s.id} status={s.status} compact />)}
                  </div>
                  <ul className="space-y-1">{settled.filter((s) => s.player_id === r.player_id).map((s) => <ResultRow key={s.id} r={s} />)}</ul>
                </div>
              ) : null}
              <div className="text-xs text-faint">Recorded {formatTimestamp(r.generated_at)}, model {r.model_version}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
