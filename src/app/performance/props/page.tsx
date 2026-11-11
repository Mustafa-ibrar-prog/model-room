import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { formatPct, formatTimestamp } from "@/lib/format";
import { loadPropValidation, type PropMetrics, type PropValidation } from "@/server/engine/board";
import { PageHeader, Panel, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import type { League } from "@/types/domain";

export const metadata: Metadata = { title: "Prop validation" };

type SP = Promise<Record<string, string | string[] | undefined>>;
const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

export default function PropValidationPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader
        title="Prop validation"
        intro="How each player-prop category has performed, the active model and the shadow experiments reported separately: held-out backtests, and every projection recorded before a game graded against what happened. Figures below the minimum sample are withheld."
      />
      <Suspense fallback={<div className="mx-auto max-w-7xl px-4 sm:px-6"><TableSkeleton rows={8} /></div>}>
        <Body searchParams={searchParams} />
      </Suspense>
    </>
  );
}

const n3 = (x: number | null | undefined) => (x == null ? "–" : x.toFixed(3));
const signed = (x: number | null | undefined) => (x == null ? "–" : `${x > 0 ? "+" : ""}${x.toFixed(2)}`);
const ROLE = { active: "Active (published)", shadow: "Shadow (recorded, not published)", previous: "Earlier version (no longer running)" } as const;

function Side({ s, label }: { s: { n: number; predicted: number | null; hit_rate: number | null }; label: string }) {
  return (
    <span>
      {label}: {s.hit_rate != null && s.predicted != null ? <>{formatPct(s.hit_rate)} happened vs {formatPct(s.predicted)} expected</> : "too few to report"} <span className="text-faint">(n {s.n})</span>
    </span>
  );
}

function LiveCells({ m }: { m: PropMetrics | undefined }) {
  if (!m || !m.player_games) return <td colSpan={6} className="py-1.5 text-faint">No graded games</td>;
  return (
    <>
      <td className="py-1.5 pr-3 text-right font-mono">{m.player_games}</td>
      <td className="pr-3 text-right font-mono">{m.mae != null ? m.mae.toFixed(2) : <span className="text-faint" title={m.withheld_mean}>withheld</span>}</td>
      <td className="pr-3 text-right font-mono">{m.bias != null ? signed(m.bias) : <span className="text-faint">withheld</span>}</td>
      <td className="pr-3 text-right font-mono">{m.brier != null ? n3(m.brier) : <span className="text-faint" title={m.withheld_ladder}>withheld</span>}</td>
      <td className="pr-3 text-right font-mono">{m.log_loss != null ? n3(m.log_loss) : <span className="text-faint">withheld</span>}</td>
      <td className="pr-3 text-right font-mono">{m.calibration_error != null ? formatPct(m.calibration_error, 1) : <span className="text-faint">withheld</span>}</td>
    </>
  );
}

function Category({ v, cat, label }: { v: PropValidation; cat: string; label: string }) {
  const versions = Object.entries(v.versions ?? {});
  const active = v.versions?.[v.active ?? ""];
  const ou = active?.live?.[cat]?.all?.over_under;
  const cal = active?.live?.[cat]?.all?.calibration;
  const th = "py-1.5 pr-3 text-right font-500 first:text-left";
  return (
    <Panel className="space-y-4 p-4">
      <h2 className="font-display text-xl font-600 text-ink">{label}</h2>

      <section className="overflow-x-auto">
        <h3 className="mb-1 text-sm font-600 text-ink">Live: recorded before each game, graded after</h3>
        <table className="w-full min-w-[40rem] text-xs">
          <thead className="text-faint">
            <tr><th className={th}>Version</th><th className={th}>Window</th><th className={th}>Player-games</th><th className={th}>MAE</th><th className={th}>Bias</th><th className={th}>Brier</th><th className={th}>Log loss</th><th className={th}>Calibration error</th></tr>
          </thead>
          <tbody>
            {versions.flatMap(([ver, x]) => (["all", "recent"] as const).map((w) => (
              <tr key={`${ver}-${w}`} className="border-t border-navy-700/70 text-mute">
                <td className="py-1.5 pr-3 text-ink">{w === "all" ? <>{ver} <span className="text-faint">· {ROLE[x.role]}</span></> : ""}</td>
                <td className="pr-3 text-right">{w === "all" ? "All" : `Last ${v.recent_window?.days ?? 14} days`}</td>
                <LiveCells m={x.live?.[cat]?.[w]} />
              </tr>
            )))}
          </tbody>
        </table>
      </section>

      {ou ? (
        <section className="text-xs text-mute">
          <h3 className="mb-1 text-sm font-600 text-ink">Over/Under, active model ({v.active})</h3>
          <p className="mb-1 text-faint">At {ou.line}; a lean is more than {Math.round((v.rules?.lean ?? 0.03) * 100)} points from 50%. No market lines are graded here.</p>
          <p className="flex flex-col gap-0.5 sm:flex-row sm:gap-4"><Side s={ou.over} label="Leaned Over" /><Side s={ou.under} label="Leaned Under" /></p>
        </section>
      ) : null}

      {cal ? (
        <section className="overflow-x-auto text-xs">
          <h3 className="mb-1 text-sm font-600 text-ink">Calibration, active model, live</h3>
          <table className="w-full min-w-[28rem]">
            <thead className="text-faint"><tr><th className={th}>Model chance</th><th className={th}>Rows</th><th className={th}>Expected</th><th className={th}>Happened</th></tr></thead>
            <tbody>
              {cal.map((b) => (
                <tr key={b.bin} className="border-t border-navy-700/70 text-mute">
                  <td className="py-1 pr-3">{b.bin}</td><td className="pr-3 text-right font-mono">{b.n}</td>
                  <td className="pr-3 text-right font-mono">{b.predicted != null ? formatPct(b.predicted, 1) : "–"}</td>
                  <td className="pr-3 text-right font-mono">{b.actual != null ? formatPct(b.actual, 1) : <span className="text-faint">too few</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="overflow-x-auto">
        <h3 className="mb-1 text-sm font-600 text-ink">Historical: held-out backtest seasons</h3>
        <table className="w-full min-w-[40rem] text-xs">
          <thead className="text-faint">
            <tr><th className={th}>Version</th><th className={th}>Seasons</th><th className={th}>Player-games</th><th className={th}>MAE</th><th className={th}>Bias</th><th className={th}>Log loss</th><th className={th}>Recent-form log loss</th><th className={th}>Calibration error</th></tr>
          </thead>
          <tbody>
            {versions.filter(([, x]) => x.role !== "previous").map(([ver, x]) => {
              const h = x.historical?.markets?.[cat];
              return (
                <tr key={ver} className="border-t border-navy-700/70 text-mute">
                  <td className="py-1.5 pr-3 text-ink">{ver}{x.historical && x.historical.version !== ver ? <span className="text-faint"> · shows {x.historical.version}&apos;s backtest</span> : null}</td>
                  {h ? (
                    <>
                      <td className="pr-3 text-right">{x.historical!.test_seasons?.join(", ")}</td>
                      <td className="pr-3 text-right font-mono">{h.player_games?.toLocaleString() ?? "–"}</td>
                      <td className="pr-3 text-right font-mono">{h.mae?.toFixed(2) ?? "–"}</td>
                      <td className="pr-3 text-right font-mono">{signed(h.bias)}</td>
                      <td className="pr-3 text-right font-mono">{n3(h.log_loss)}</td>
                      <td className="pr-3 text-right font-mono">{n3(h.baseline_log_loss)}</td>
                      <td className="pr-3 text-right font-mono">{h.calibration_error != null ? formatPct(h.calibration_error, 1) : "–"}</td>
                    </>
                  ) : <td colSpan={7} className="text-faint">No backtest recorded for this version and category</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
        {versions.filter(([, x]) => x.historical_note).map(([ver, x]) => <p key={ver} className="mt-1 text-[0.7rem] text-faint">{ver}: {x.historical_note}</p>)}
      </section>
    </Panel>
  );
}

async function Body({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const league: League = one(sp.sport) === "nba" ? "nba" : "nfl";
  const v = await loadPropValidation(league);
  const tabs = (
    <div role="tablist" aria-label="Sport" className="flex w-fit gap-1 rounded-full bg-navy-850 p-1">
      {(["nfl", "nba"] as const).map((l) => (
        <Link key={l} role="tab" aria-selected={l === league} href={`/performance/props?sport=${l}`}
          className={`rounded-full px-4 py-1 font-display text-sm font-600 uppercase tracking-wider ${l === league ? "bg-model text-navy-950" : "text-mute hover:text-ink"}`}>{l}</Link>
      ))}
    </div>
  );
  if (!v || v.error || !v.versions) {
    return <div className="mx-auto max-w-7xl space-y-4 px-4 pb-16 sm:px-6">{tabs}<Unavailable title="Validation report not built yet" body={v?.error ? "The last refresh could not build it; the props themselves are unaffected." : "It is built with each data refresh."} /></div>;
  }
  const cats = Object.entries(v.markets ?? {});
  const cat = one(sp.cat);
  const shown = cat && v.markets?.[cat] ? cats.filter(([k]) => k === cat) : cats;
  const r = v.rules!;
  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 pb-16 sm:px-6">
      {tabs}
      <nav aria-label="Categories" className="-mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Link href={`/performance/props?sport=${league}`} className={`shrink-0 rounded-full px-3 py-1.5 text-sm ${!cat ? "bg-ink text-navy-950" : "bg-navy-850 text-mute hover:text-ink"}`}>All</Link>
        {cats.map(([k, lab]) => (
          <Link key={k} href={`/performance/props?sport=${league}&cat=${k}`} className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm ${cat === k ? "bg-ink text-navy-950" : "bg-navy-850 text-mute hover:text-ink"}`}>{lab}</Link>
        ))}
      </nav>
      <p className="text-xs leading-relaxed text-mute">
        Built {formatTimestamp(v.generated_at ?? null)}. Live figures use each version&apos;s last projection before the game, players who played. Withheld below {r.min_player_games} player-games
        (MAE, bias) or {r.min_ladder_rows} ladder rows (Brier, log loss, calibration); a calibration bin needs {r.min_bin} rows and an Over/Under side {r.min_side} player-games.
        Ladder rows from one player-game are correlated, so these are descriptions, not independent tests. {v.evidence_labels?.note} Strong historical support: {v.evidence_labels?.strong_historical_support}.
      </p>
      {shown.map(([k, lab]) => <Category key={k} v={v} cat={k} label={lab} />)}
    </div>
  );
}
