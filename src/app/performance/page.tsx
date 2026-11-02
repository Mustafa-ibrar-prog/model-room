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
import { PageHeader, Panel, Section, TableSkeleton, Unavailable } from "@/components/ui/primitives";

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

async function Body({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const league: League = sp.sport === "nba" ? "nba" : "nfl";
  const [props, live] = await Promise.all([loadPropsBoard(league), getPerformance(league)]);
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

      <Section title="Live record" intro="Projections recorded before each game this season and last, graded once the game was final.">
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
