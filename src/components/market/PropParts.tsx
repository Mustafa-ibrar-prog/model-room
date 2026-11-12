/**
 * Player-prop card pieces (P1). Two independent outputs, never mixed:
 *   Market (white): a line some market actually lists, its provider and when it was seen. Or plainly "No market line".
 *   Model Room (blue): the model's own projected stat, its distribution, and its probabilities at the market's line.
 * The preferred outcome comes from those probabilities at the exact line (lib/propOutcome), never from mean vs line.
 */
import { formatPct, formatTimestamp } from "@/lib/format";
import { providerName } from "@/lib/providers";
import { ladderBars, lineText, type Ladder, type LineProbs, type Preferred } from "@/lib/propOutcome";
import type { ContributionView } from "@/server/data/explorer";
import type { League } from "@/types/domain";
import type { PropLineView } from "@/types/props";
import { age, fmt } from "./bits";

export type PreferredView = Preferred | { kind: "none"; reason: "stale_line" };

const CONTRACT = (l: PropLineView) => (l.op === ">=" ? `“${lineText(l.threshold)}+” contract` : `“over ${lineText(l.threshold)}” contract`);

/** Who quotes the line (the usable quote's exchange, else the latest quote's). */
export function lineProvider(l: PropLineView): string | null {
  const q = l.market ?? [...l.quotes].sort((a, b) => b.capturedAt.localeCompare(a.capturedAt))[0];
  return q ? providerName(q.provider).replace(" US", "") : null;
}

/** The market's line, or the plain statement that there is none. */
export function MarketBox({ l, observed, now, stale, compact = false }: { l: PropLineView | null; observed: string | null; now: number; stale: boolean; compact?: boolean }) {
  if (!l) {
    return (
      <section aria-label="Market line" className="rounded-md border border-dashed border-navy-600 px-3 py-2">
        <div className="text-[0.68rem] text-faint">Market line</div>
        <div className={`${compact ? "text-sm" : "text-base"} pt-0.5 text-mute`}>None available</div>
        {!compact ? <p className="mt-1 text-xs text-faint">No market lists this prop. Model Room does not borrow a line from another provider or invent one.</p> : null}
      </section>
    );
  }
  const by = lineProvider(l);
  return (
    <section aria-label="Market line" className={`rounded-md border px-3 py-2 ${stale ? "border-edge/70" : "border-navy-600"}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[0.68rem] text-ink">Market line</span>
        {observed ? <span className={`text-[0.65rem] ${stale ? "text-edge" : "text-faint"}`}>{stale ? `Last seen ${age(observed, now)} · may have moved` : `seen ${age(observed, now)}`}</span> : null}
      </div>
      <div className={`font-mono font-600 text-ink ${compact ? "text-xl" : "text-3xl"} leading-tight`}>{lineText(l.op === ">=" ? l.threshold - 0.5 : l.threshold)}</div>
      <div className="text-[0.68rem] text-mute">{by ?? "Market"} · {CONTRACT(l)}</div>
    </section>
  );
}

/** Model Room's own projected stat: the simulated average, with the middle outcome and typical range. */
export function ModelBox({ mean, median, range80, supportLabel, supportCls, compact = false }: { mean: number; median: number; range80: [number, number]; supportLabel: string; supportCls: string; compact?: boolean }) {
  return (
    <section aria-label="Model Room projection" className="rounded-md border border-navy-700 px-3 py-2">
      <div className="text-[0.68rem] text-model">Model Room projection</div>
      <div className={`font-mono font-600 text-model ${compact ? "text-xl" : "text-3xl"} leading-tight`}>{mean >= 100 ? mean.toFixed(0) : mean.toFixed(1)}</div>
      <div className="text-[0.68rem] text-mute">
        average · middle {fmt(median)} · range {fmt(range80[0])}–{fmt(range80[1])}
      </div>
      {supportLabel ? <div className={`text-[0.65rem] ${supportCls}`}>{supportLabel}</div> : null}
    </section>
  );
}

const pushText = (pr: LineProbs, l: PropLineView | null) =>
  pr.push === null ? "not estimated (yards are simulated as continuous)" : l && pr.push === 0 ? "not possible on this contract" : pr.push === 0 ? "not possible at a half-point line" : formatPct(pr.push);

/** Over / Push / Under at the market line, from the model's distribution. */
export function OutcomeBar({ pr, l, compact = false }: { pr: LineProbs; l: PropLineView | null; compact?: boolean }) {
  const push = pr.push ?? 0;
  return (
    <section aria-label={`Model Room chance at ${lineText(pr.line)}`}>
      {!compact ? <h3 className="mb-1 text-xs font-600 text-ink">Model Room chance at {lineText(pr.line)}</h3> : null}
      <div className="flex h-2 overflow-hidden rounded-full bg-navy-700" aria-hidden="true">
        <div className="bg-model" style={{ width: `${pr.over * 100}%` }} />
        {push > 0 ? <div className="bg-faint/60" style={{ width: `${push * 100}%` }} /> : null}
      </div>
      <div className={`mt-1 flex justify-between gap-2 ${compact ? "text-[0.7rem]" : "text-xs"}`}>
        <span className="text-ink">Over {formatPct(pr.over)}</span>
        {!compact ? <span className="text-faint">Push: {pushText(pr, l)}</span> : push > 0 ? <span className="text-faint">Push {formatPct(push)}</span> : null}
        <span className="text-mute">Under {formatPct(pr.under)}</span>
      </div>
    </section>
  );
}

const NONE: Record<string, string> = {
  no_market_line: "No preferred outcome without a market line.",
  insufficient_history: "Too little player history: no preferred outcome.",
  outside_range: "The line is outside the model's simulated range: no preferred outcome.",
  stale_line: "The market line is stale and may have moved: no preferred outcome.",
};

export function PreferredChip({ p, line }: { p: PreferredView; line: number | null }) {
  if (p.kind === "side") {
    return (
      <div className="flex items-center justify-between gap-2 rounded-md bg-navy-850 px-3 py-1.5 text-sm">
        <span className="font-600 text-ink">Prefers {p.side === "over" ? "Over" : "Under"} {line != null ? lineText(line) : ""}</span>
        <span className="font-mono text-xs text-mute">{formatPct(p.prob)}</span>
      </div>
    );
  }
  if (p.kind === "close") {
    return <div className="rounded-md bg-navy-850 px-3 py-1.5 text-sm text-mute">Too close to call <span className="text-xs text-faint">· within 3 points of even</span></div>;
  }
  return p.reason === "no_market_line" ? null : <div className="rounded-md bg-navy-850 px-3 py-1.5 text-xs text-faint">{NONE[p.reason]}</div>;
}

/** The detail view's preferred-outcome block, with its reasoning. */
export function PreferredBlock({ p, pr, mean }: { p: PreferredView; pr: LineProbs | null; mean: number }) {
  return (
    <section aria-label="Preferred outcome" className="space-y-1.5 rounded-md bg-navy-850 p-3">
      <h3 className="text-xs font-600 text-ink">Preferred outcome</h3>
      {p.kind === "side" && pr ? (
        <>
          <p className="font-display text-2xl font-700 text-ink">{p.side === "over" ? "Over" : "Under"} {lineText(pr.line)} · {formatPct(p.prob)}</p>
          {p.againstAverage ? (
            <p className="text-xs text-mute">
              The average ({fmt(mean)}) sits {mean > pr.line ? "above" : "below"} the line, but more of the simulated outcomes land {p.side === "under" ? "below" : "above"} it. The preference follows the chance, not the average.
            </p>
          ) : null}
          {pr.push && pr.push > 0 ? <p className="text-xs text-mute">Pushes set aside: {p.side === "over" ? "Over" : "Under"} {formatPct(p.noPushProb)}.</p> : null}
        </>
      ) : p.kind === "close" && pr ? (
        <p className="text-sm text-mute">Too close to call: Over {formatPct(pr.over)}, Under {formatPct(pr.under)}. Within 3 points of even with pushes set aside, so no side is preferred.</p>
      ) : (
        <p className="text-sm text-mute">{NONE[(p as { reason: string }).reason] ?? NONE.no_market_line}</p>
      )}
      <p className="text-[0.68rem] text-faint">From Model Room&apos;s own probability at this exact line. Not a betting recommendation: prop probabilities have not been validated against market prices.</p>
    </section>
  );
}

/** The model's distribution (probability per outcome, from the calibrated ladder), with the line marked. */
export function DistributionChart({ grid, line, label }: { grid: Ladder; line: number | null; label: string }) {
  const bars = ladderBars(grid).filter((b) => b.p > 0.0005 || b.from === 0);
  if (bars.length < 2) return null;
  const max = Math.max(...bars.map((b) => b.p));
  const count = grid.step === 1;
  const clears = (b: (typeof bars)[number]) => line != null && (count ? b.from > line : b.from >= line);
  const every = Math.max(1, Math.ceil(bars.length / 8));
  const cut = line == null ? -1 : bars.findIndex((b) => clears(b));
  const text = (b: (typeof bars)[number], i: number) => (i === 0 && b.to != null && b.to !== b.from && b.from === 0 ? (count ? `≤${b.to}` : `<${b.to}`) : i === bars.length - 1 && b.to == null ? `${b.from}+` : `${b.from}`);
  return (
    <figure className="m-0" role="img" aria-label={`Model Room distribution of ${label}${line != null ? ` with the line at ${lineText(line)}` : ""}`}>
      <div className="flex h-24 items-end gap-px">
        {bars.map((b, i) => (
          <div key={b.from} className="flex h-full flex-1 items-end">
            {i === cut ? <div className="mr-px h-full w-0.5 shrink-0 bg-ink" aria-hidden="true" /> : null}
            <div className={`w-full rounded-t-sm ${clears(b) ? "bg-model" : "bg-navy-600"}`} style={{ height: `${Math.max(2, (b.p / max) * 100)}%` }} title={`${text(b, i)}${!count && b.to != null ? `–${b.to}` : ""}: ${formatPct(b.p, 1)}`} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-px font-mono text-[0.6rem] text-faint">
        {bars.map((b, i) => <span key={b.from} className="flex-1 text-center">{i % every === 0 || i === bars.length - 1 ? text(b, i) : ""}</span>)}
      </div>
      <figcaption className="mt-1 text-[0.68rem] text-faint">
        {line != null ? <>Blue: outcomes that clear {lineText(line)}. White rule: the line. </> : null}
        {count ? "One bar per outcome." : "One bar per 5 yards."} Heights are the model&apos;s calibrated chance of each outcome.
      </figcaption>
    </figure>
  );
}

// ------------------------------------------------------------------ explanation (P3)
const SENT: Record<League, Record<string, string>> = {
  nba: {
    baseline: "His recent per-minute rates at his usual minutes",
    minutes: "Projected minutes (filling the team's 240, including minutes freed by absent teammates)",
    blowout: "Projected margin trims starters' minutes",
    usage: "Teammates treated as out: a bigger share of the scoring and assists",
    pace: "Projected pace against his team's usual",
    matchup: "Opponent's defense against his position",
    simulation: "Simulation (minutes kept within 1–48 and random variation)",
  },
  nfl: {
    baseline: "His usual share and efficiency at his team's usual volume, against an average opponent",
    game_environment: "Team volume this game (opponent's usual plays faced, projected margin and total)",
    opportunity: "Recent snap-share trend",
    matchup_share: "Opponent's target share allowed to his position",
    lineup: "Share scaling across the active roster (includes teammates ruled Out or Doubtful)",
    matchup_efficiency: "Opponent's efficiency allowed (catch rate, yards, coverage, blitz)",
    other: "Inexperienced starting QB adjustment",
    simulation: "Simulation (volume rounding and limits, random variation)",
  },
};

const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v) >= 10 ? Math.abs(v).toFixed(0) : Math.abs(v).toFixed(1)}`;

export function Contributions({ c, league }: { c: ContributionView; league: League }) {
  if (!c.steps) {
    return <p className="text-xs text-faint">Adjustments not recorded separately: {c.reason}. Only the final projection is shown.</p>;
  }
  return (
    <div className="space-y-1">
      <dl className="space-y-0.5 text-xs">
        {c.steps.map((s) => (
          <div key={s.key} className="flex justify-between gap-3">
            <dt className={s.key === "baseline" ? "text-ink" : "text-mute"}>{SENT[league][s.key] ?? s.key.replaceAll("_", " ")}</dt>
            <dd className={`shrink-0 font-mono ${s.key === "baseline" ? "text-ink" : Math.abs(s.value) < 0.05 ? "text-faint" : "text-mute"}`}>{s.key === "baseline" ? s.value.toFixed(1) : signed(s.value)}</dd>
          </div>
        ))}
        {c.final != null ? (
          <div className="flex justify-between gap-3 border-t border-navy-700 pt-0.5"><dt className="text-model">Model Room average</dt><dd className="font-mono text-model">{c.final.toFixed(1)}</dd></div>
        ) : null}
      </dl>
      {league === "nba" && c.minutes ? <p className="text-[0.68rem] text-faint">Minutes: usual {c.minutes.usual.toFixed(1)} · projected {c.minutes.projected.toFixed(1)}.</p> : null}
      <p className="text-[0.68rem] text-faint">Recorded by the model when it made this projection. Steps are applied in this order; each figure is the change at that step.</p>
    </div>
  );
}

// ------------------------------------------------------------------ injuries and freshness
type InjRow = { player: string; position: string | null; status: string; source: string; reportTime: string | null };

const USE: Record<League, { own: string; opp: string }> = {
  nba: {
    own: "Not read by the active NBA model: it treats a rotation player who missed his team's last 2 games as out.",
    opp: "Not used by the model.",
  },
  nfl: {
    own: "Used: Out and Doubtful players are removed from the projection; Questionable players are projected as playing.",
    opp: "Not used by the model.",
  },
};

function InjList({ rows }: { rows: InjRow[] }) {
  if (!rows.length) return <p className="text-faint">None listed.</p>;
  const order = { out: 0, doubtful: 1, questionable: 2 } as Record<string, number>;
  return (
    <ul className="space-y-0.5">
      {[...rows].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3)).slice(0, 8).map((r) => (
        <li key={`${r.player}-${r.status}`}><span className={r.status === "questionable" ? "text-edge" : "text-ink"}>{r.status[0].toUpperCase() + r.status.slice(1)}</span>: {r.player}{r.position ? ` (${r.position})` : ""}</li>
      ))}
    </ul>
  );
}

export function InjuriesFreshness({ league, team, opp, injuries, modelAbsences, generatedAt, feedAt, lineSeen, version }: {
  league: League; team: string; opp: string; injuries: { team: string; rows: InjRow[] }[] | null; modelAbsences: string | null;
  generatedAt: string; feedAt: string | null; lineSeen: string | null; version: string;
}) {
  const own = injuries?.find((i) => i.team === team)?.rows ?? null;
  const theirs = injuries?.find((i) => i.team === opp)?.rows ?? null;
  return (
    <section aria-label="Injuries and freshness" className="grid grid-cols-1 gap-3 border-t border-navy-700 pt-3 text-xs text-mute sm:grid-cols-2">
      <div>
        <h4 className="text-[0.65rem] text-faint">His team ({team}) · injury report</h4>
        {own ? <InjList rows={own} /> : <p className="text-faint">No injury feed this refresh.</p>}
        <p className="mt-0.5 text-[0.68rem] text-faint">{USE[league].own}</p>
        {league === "nba" ? <p className="mt-0.5 text-[0.68rem] text-mute">Treated as out by the model: {modelAbsences ?? "nobody"}.</p> : null}
      </div>
      <div>
        <h4 className="text-[0.65rem] text-faint">Opponent ({opp}) · injury report</h4>
        {theirs ? <InjList rows={theirs} /> : <p className="text-faint">No injury feed this refresh.</p>}
        <p className="mt-0.5 text-[0.68rem] text-faint">{USE[league].opp}</p>
      </div>
      <div>
        <h4 className="text-[0.65rem] text-faint">Model run</h4>
        <p>{formatTimestamp(generatedAt)} · {league.toUpperCase()} props {version}</p>
        <p className="text-faint">Injury feed {feedAt ? formatTimestamp(feedAt) : "not available"}</p>
      </div>
      <div>
        <h4 className="text-[0.65rem] text-faint">Market line observed</h4>
        <p>{lineSeen ? formatTimestamp(lineSeen) : "No market line"}</p>
      </div>
    </section>
  );
}
