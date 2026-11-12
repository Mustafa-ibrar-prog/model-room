import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { formatPct } from "@/lib/format";
import { CATEGORIES } from "@/server/data/explorer";
import { getPerformance } from "@/server/data/history";
import { loadPropsBoard } from "@/server/engine/board";
import type { League } from "@/types/domain";
import type { ProbBlock } from "@/types/history";
import { ModelPerformance } from "@/components/tables/ModelPerformance";
import { ResultRow, StatusLegend } from "@/components/results/SettlementBits";
import { AutoSubmit } from "@/components/props/AutoSubmit";
import { LockedPanel, PageHeader, Panel, Section, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import { providerName } from "@/lib/providers";
import { getMarketResults, type MarketResultsView } from "@/server/data/marketResults";
import { getViewer } from "@/server/viewer";
import { isLocked } from "@/types/domain";
import type { ResultBlock } from "@/types/marketResults";

export const metadata: Metadata = { title: "Model performance" };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default function PerformancePage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader
        title="Performance"
        intro="How the models have done: held-out backtests, and every projection recorded before a game graded against what happened. Sample sizes are shown everywhere; small ones are noise."
      />
      <Suspense fallback={<div className="mx-auto max-w-7xl px-4 sm:px-6"><TableSkeleton rows={8} /></div>}>
        <Body searchParams={searchParams} />
      </Suspense>
    </>
  );
}

const label = (league: League, key: string) => CATEGORIES[league].find((c) => c.key === key)?.label ?? key.replaceAll("_", " ");
const num = (x: number | null | undefined, d = 3) => (x == null ? "–" : x.toFixed(d));
const th = "py-1.5 pr-3 text-right font-500 first:text-left";
const td = "py-1.5 pr-3 text-right font-mono first:text-left first:font-sans";

function Calibration({ rows }: { rows: { bin: string; n: number; predicted: number; actual: number }[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[28rem] text-sm">
        <caption className="pb-2 text-left text-faint">Hit rate by model probability. A calibrated model&apos;s actual rate matches its predicted rate in every row.</caption>
        <thead className="text-faint">
          <tr><th className={th}>Probability</th><th className={th}>Lines</th><th className={th}>Predicted</th><th className={th}>Actual</th><th className={`${th} w-1/3`}><span className="sr-only">Chart</span></th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.bin} className="border-t border-navy-700/70">
              <td className={td}>{r.bin.replace("-0.0", "0.0").replace("-", "–")}</td>
              <td className={td}>{r.n.toLocaleString()}</td>
              <td className={td}>{formatPct(r.predicted, 1)}</td>
              <td className={td}>{formatPct(r.actual, 1)}</td>
              <td className="py-1.5">
                <div className="relative h-2 rounded bg-navy-800" aria-hidden="true">
                  <div className="absolute inset-y-0 left-0 rounded bg-model/40" style={{ width: `${r.predicted * 100}%` }} />
                  <div className="absolute inset-y-[-2px] w-0.5 bg-ink" style={{ left: `${r.actual * 100}%` }} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BlockTable({ rows, first }: { rows: (ProbBlock & { key: string })[]; first: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] text-sm">
        <thead className="text-faint">
          <tr><th className={th}>{first}</th><th className={th}>Lines</th><th className={th}>Brier</th><th className={th}>Log loss</th><th className={th}>Avg prob</th><th className={th}>Hit rate</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-navy-700/70">
              <td className={td}>{r.key}</td><td className={td}>{r.n.toLocaleString()}</td><td className={td}>{num(r.brier)}</td>
              <td className={td}>{num(r.log_loss)}</td><td className={td}>{formatPct(r.avg_predicted, 1)}</td><td className={td}>{formatPct(r.hit_rate, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

function ResultsTable({ first, rows }: { first: string; rows: [string, ResultBlock][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] text-sm">
        <thead className="text-faint">
          <tr><th className={th}>{first}</th><th className={th}>Settled</th><th className={th}>Correct</th><th className={th}>Incorrect</th><th className={th}>Void</th><th className={th}>Pending</th><th className={th}>Hit rate</th><th className={th}>Brier</th></tr>
        </thead>
        <tbody>
          {rows.map(([k, b]) => (
            <tr key={k} className="border-t border-navy-700/70">
              <td className={td}>{k}</td><td className={td}>{b.settled}</td><td className={`${td} text-good`}>{b.won}</td><td className={`${td} text-danger`}>{b.lost}</td>
              <td className={td}>{b.void}</td><td className={`${td} text-pending`}>{b.pending}</td><td className={td}>{b.win_pct != null ? formatPct(b.win_pct, 1) : "–"}</td><td className={td}>{num(b.brier)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SettledRecord({ league, v }: { league: League; v: MarketResultsView }) {
  const o = v.overall;
  const sel = "rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm text-ink";
  const withheld = Object.entries(v.withheld);
  if (!v.available || o.predictions === 0) {
    return (
      <div className="space-y-3">
        <StatusLegend />
        <Unavailable
          title="No market-settled predictions yet"
          body={
            withheld.length
              ? `Settled predictions exist for ${withheld.map(([p, n]) => `${providerName(p)} (${n})`).join(", ")}, but that provider's data can't be published under its terms, so they're kept off this site.`
              : "Grading starts once exchange prices are connected: each prediction made against a Polymarket US or Kalshi market is graded when that exchange settles it. Exchange data isn't connected on this site yet."
          }
        />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <StatusLegend />
      <form action="/performance" className="flex flex-wrap items-end gap-3">
        <input type="hidden" name="sport" value={league} />
        <label className="flex flex-col gap-1 text-xs text-faint">From<input type="date" name="from" defaultValue={v.query.from} className={sel} /></label>
        <label className="flex flex-col gap-1 text-xs text-faint">To<input type="date" name="to" defaultValue={v.query.to} className={sel} /></label>
        <label className="flex flex-col gap-1 text-xs text-faint">Provider
          <select name="provider" defaultValue={v.query.provider ?? ""} className={sel}><option value="">All</option>{v.providerKeys.map((p) => <option key={p} value={p}>{providerName(p)}</option>)}</select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-faint">Market
          <select name="market" defaultValue={v.query.market ?? ""} className={sel}><option value="">All</option>{v.markets.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-faint">Show
          <select name="status" defaultValue={v.query.status ?? ""} className={sel}><option value="">All</option><option value="won">Correct</option><option value="lost">Incorrect</option><option value="void">Void</option><option value="pending">Pending</option></select>
        </label>
        <button type="submit" className="rounded-full bg-model px-4 py-1.5 text-sm font-600 text-navy-950">Apply</button>
        <AutoSubmit inputs />
      </form>
      <Panel className="p-5">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-6">
          <div><dt className="text-xs text-faint">Settled</dt><dd className="font-display text-2xl font-600 text-ink">{o.settled}</dd></div>
          <div><dt className="text-xs text-faint">Correct</dt><dd className="font-display text-2xl font-600 text-good">{o.won}</dd></div>
          <div><dt className="text-xs text-faint">Incorrect</dt><dd className="font-display text-2xl font-600 text-danger">{o.lost}</dd></div>
          <div><dt className="text-xs text-faint">Void / refunded</dt><dd className="font-display text-2xl font-600 text-mute">{o.void}</dd></div>
          <div><dt className="text-xs text-faint">Pending</dt><dd className="font-display text-2xl font-600 text-pending">{o.pending}</dd></div>
          <div><dt className="text-xs text-faint">Hit rate</dt><dd className="font-display text-2xl font-600 text-ink">{o.win_pct != null ? formatPct(o.win_pct, 1) : "–"}</dd></div>
        </dl>
        {o.n_scored ? (
          <p className="mt-3 text-sm text-mute">
            On {o.n_scored} settled Yes/No markets: model Brier {num(o.brier)}, log loss {num(o.log_loss)}
            {o.market ? `; the market's own price at the time: Brier ${num(o.market.brier)}, log loss ${num(o.market.log_loss)} (n ${o.market.n})` : ""}. Lower is better.
          </p>
        ) : null}
        <p className="mt-2 text-xs text-faint">
          &quot;Correct&quot; means the side the model favoured (over 50%) is the side the exchange settled. This is prediction accuracy, not betting profit: no
          trades were placed, so no ROI is claimed.
        </p>
      </Panel>
      <Panel className="p-5"><ResultsTable first="Market" rows={Object.entries(v.byMarket)} /></Panel>
      <Panel className="p-5"><ResultsTable first="Provider" rows={Object.entries(v.byProvider).map(([k, b]) => [providerName(k), b])} /></Panel>
      <Panel className="p-5"><ResultsTable first="Month" rows={Object.entries(v.byMonth).reverse()} /></Panel>
      {v.calibration.length ? <Panel className="p-5"><Calibration rows={v.calibration} /></Panel> : null}
      {isLocked(v.records) ? (
        <LockedPanel requires={v.records.requires} title="Every settled prediction is on Pro" body="Open any settled prediction to compare the original projection, the market price then, and the exchange's official result." />
      ) : (
        <ul className="space-y-1.5">{v.records.map((r) => <ResultRow key={r.id} r={r} />)}</ul>
      )}
      {withheld.length ? <p className="text-xs text-faint">Not shown under provider terms: {withheld.map(([p, n]) => `${providerName(p)} ${n}`).join(", ")}.</p> : null}
    </div>
  );
}

async function Body({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const league: League = sp.sport === "nba" ? "nba" : "nfl";
  const viewer = await getViewer();
  const [props, live, settled] = await Promise.all([
    loadPropsBoard(league),
    getPerformance(league),
    getMarketResults(league, viewer.tier, { from: one(sp.from), to: one(sp.to), provider: one(sp.provider), market: one(sp.market), status: one(sp.status) }),
  ]);
  const bt = props.ok ? props.board.performance.backtest : null;
  return (
    <>
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div role="tablist" aria-label="Sport" className="flex gap-2">
          {(["nfl", "nba"] as const).map((l) => (
            <Link key={l} role="tab" aria-selected={l === league} href={`/performance?sport=${l}`}
              className={`rounded-md border px-4 py-2 font-display text-base font-600 uppercase tracking-wider ${l === league ? "border-model bg-model text-navy-950" : "border-navy-700 bg-navy-900 text-ink"}`}>
              {l}
            </Link>
          ))}
        </div>
      </div>

      <Section title="Game model" intro="Held-out seasons the model never saw while it was tuned.">
        <ModelPerformance league={league} />
      </Section>

      <Section title="Player props backtest" intro="Every threshold the model priced in the test seasons, scored against the result.">
        <p className="mb-3 text-sm"><Link href={`/performance/props?sport=${league}`} className="text-model hover:underline">Validation by prop category</Link> <span className="text-mute">· active model and shadow experiments, live and held-out</span></p>
        {!bt ? (
          <Unavailable title="No props backtest published yet" body="It appears here once the props backtest has run for this sport." />
        ) : (
          <div className="space-y-4">
            <Panel className="p-5">
              <p className="text-sm text-mute">Seasons {bt.test_seasons.join(", ")}, {bt.thresholds.toLocaleString()} lines, model {bt.model_version}.</p>
              {bt.overall_vs_baseline ? (
                <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div><dt className="text-xs text-faint">Log loss</dt><dd className="font-display text-2xl font-600 text-model">{num(bt.overall_vs_baseline.model.log_loss)}</dd></div>
                  <div><dt className="text-xs text-faint">Baseline log loss</dt><dd className="font-display text-2xl font-600 text-mute">{num(bt.overall_vs_baseline.baseline.log_loss)}</dd></div>
                  <div><dt className="text-xs text-faint">Brier</dt><dd className="font-display text-2xl font-600 text-model">{num(bt.overall_vs_baseline.model.brier)}</dd></div>
                  <div><dt className="text-xs text-faint">Baseline Brier</dt><dd className="font-display text-2xl font-600 text-mute">{num(bt.overall_vs_baseline.baseline.brier)}</dd></div>
                </dl>
              ) : null}
              <p className="mt-3 text-xs text-faint">The baseline is how often the player cleared each line in their recent games. Lower is better on both scores.</p>
            </Panel>
            <Panel className="p-5">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-sm">
                  <caption className="pb-2 text-left text-faint">By stat</caption>
                  <thead className="text-faint">
                    <tr><th className={th}>Stat</th><th className={th}>Lines</th><th className={th}>Log loss</th><th className={th}>Baseline</th><th className={th}>Brier</th><th className={th}>Avg miss</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(bt.by_market).sort((a, b) => b[1].n - a[1].n).map(([k, m]) => (
                      <tr key={k} className="border-t border-navy-700/70">
                        <td className={td}>{label(league, k)}</td><td className={td}>{m.n.toLocaleString()}</td>
                        <td className={`${td} ${m.baseline_log_loss != null && m.log_loss < m.baseline_log_loss ? "text-good" : ""}`}>{num(m.log_loss)}</td>
                        <td className={td}>{num(m.baseline_log_loss)}</td><td className={td}>{num(m.brier)}</td><td className={td}>{num(m.mean_mae, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
            {bt.calibration ? <Panel className="p-5"><Calibration rows={bt.calibration} /></Panel> : null}
            {bt.notes.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-mute">{bt.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
          </div>
        )}
      </Section>

      <Section title="Settled market record" intro="Predictions made against real Polymarket US and Kalshi markets, graded on each market's official settlement.">
        <SettledRecord league={league} v={settled} />
      </Section>

      <Section title="Live record (box scores)" intro="Every projection recorded before each game this season and last, scored against the final box score. This measures projection accuracy, separately from market settlement.">
        {!live || (!live.games && !live.props) ? (
          <Unavailable title="Nothing graded yet" body="The live record fills in as games recorded by the model go final." />
        ) : (
          <div className="space-y-4">
            {live.games ? (
              <Panel className="p-5">
                <h3 className="font-display text-lg font-600 text-ink">Games ({live.games.n})</h3>
                <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div><dt className="text-xs text-faint">Margin error (avg)</dt><dd className="font-mono text-lg text-ink">{live.games.margin_mae.toFixed(2)}</dd></div>
                  <div><dt className="text-xs text-faint">Total error (avg)</dt><dd className="font-mono text-lg text-ink">{live.games.total_mae.toFixed(2)}</dd></div>
                  <div><dt className="text-xs text-faint">Winner picked</dt><dd className="font-mono text-lg text-ink">{live.games.winner_correct == null ? "–" : formatPct(live.games.winner_correct, 1)}</dd></div>
                  <div><dt className="text-xs text-faint">Win-prob Brier</dt><dd className="font-mono text-lg text-ink">{num(live.games.win_prob.brier)}</dd></div>
                </dl>
              </Panel>
            ) : null}
            {live.props ? (
              <>
                <Panel className="p-5"><BlockTable first="Stat" rows={Object.entries(live.props.by_market).map(([k, b]) => ({ key: label(league, k), ...b })).sort((a, b) => b.n - a.n)} /></Panel>
                <Panel className="p-5"><Calibration rows={live.props.calibration} /></Panel>
                <Panel className="p-5"><BlockTable first="Date" rows={[...live.props.by_date].reverse().slice(0, 30).map((d) => ({ key: d.date, ...d }))} /></Panel>
                <Panel className="p-5"><BlockTable first="Player" rows={live.props.by_player.slice(0, 40).map((d) => ({ key: d.player, ...d }))} /></Panel>
              </>
            ) : (
              <p className="text-sm text-mute">No player-prop projection has been graded yet.</p>
            )}
            <p className="text-xs text-faint">{live.note}</p>
          </div>
        )}
      </Section>
    </>
  );
}
