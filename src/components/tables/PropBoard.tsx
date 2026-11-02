import Link from "next/link";
import { formatKickoff, formatPct, formatTimestamp } from "@/lib/format";
import { getProps } from "@/server/data/props";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import type { PropLineView, PropMarketView, PropPlayerView } from "@/types/props";
import { LockedPanel, Panel, SourceStamp, Unavailable } from "@/components/ui/primitives";

const PROVIDER: Record<string, string> = { polymarket_us: "Polymarket US", kalshi: "Kalshi" };
const VARIANT: Record<string, string> = { espn_ppr: "ESPN scoring", sleeper_ppr: "Sleeper scoring" };
const POS_ORDER: Record<string, number> = { QB: 0, RB: 1, WR: 2, TE: 3 };

function providerName(p: string): string {
  return p.startsWith("manual:") ? p.slice(7) : (PROVIDER[p] ?? p);
}

function lineText(l: PropLineView): string {
  const n = Number.isInteger(l.threshold) ? l.threshold.toFixed(0) : l.threshold.toFixed(1);
  const base = l.op === ">=" ? `${n}+` : `Over ${n}`;
  return l.variant ? `${base} (${VARIANT[l.variant] ?? l.variant})` : base;
}

/** The line to show first: one with a usable market price nearest a coin flip, else the model's nearest. */
function headline(m: PropMarketView): PropLineView | null {
  if (!m.lines.length) return null;
  const priced = m.lines.filter((l) => l.market);
  const pool = priced.length ? priced : m.lines;
  return [...pool].sort((a, b) => Math.abs(a.modelProb - 0.5) - Math.abs(b.modelProb - 0.5))[0];
}

function fmtStat(n: number): string {
  return Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(1);
}

function Edge({ l }: { l: PropLineView }) {
  if (l.edge) {
    const strong = l.edge.grade === "strong";
    return (
      <span>
        <span className={`font-display text-[1.05rem] font-600 ${strong ? "text-edge" : "text-mute"}`}>
          {strong ? "Strong: " : "Lean: "}
          {l.edge.side === "yes" ? "Yes" : "No"} +{(l.edge.ev * 100).toFixed(1)}¢
        </span>
        <span className="ml-1 text-xs text-mute">per $1 at {providerName(l.edge.provider)}</span>
        {!strong && l.edge.reasons.length ? <span className="block text-xs text-faint">Not strong: {l.edge.reasons.join("; ")}</span> : null}
      </span>
    );
  }
  if (l.market) return <span className="text-sm text-mute">No edge after fees</span>;
  const why = l.quotes.find((q) => !q.usable)?.flags[0];
  return <span className="text-sm text-faint">{l.quotes.length ? `Market unusable: ${why}` : "Market unavailable"}</span>;
}

function MarketCell({ l }: { l: PropLineView }) {
  if (!l.market || l.market.mid === null) return <span className="text-sm text-faint">—</span>;
  return (
    <span>
      <span className="font-display text-[1.05rem] font-600 text-market">{formatPct(l.market.mid)}</span>
      <span className="ml-1.5 text-xs text-mute">
        {providerName(l.market.provider)} {l.market.bid !== null && l.market.ask !== null ? `${(l.market.bid * 100).toFixed(0)}/${(l.market.ask * 100).toFixed(0)}¢` : ""}
      </span>
    </span>
  );
}

function MarketRow({ m }: { m: PropMarketView }) {
  const h = headline(m);
  const others = m.lines.filter((l) => l !== h);
  return (
    <div className="border-t border-navy-700/60 py-2.5 first:border-t-0">
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 md:grid-cols-[1.3fr_1.1fr_0.8fr_0.6fr_1fr_1.6fr] md:items-baseline">
        <div className="text-[0.95rem] text-ink">
          {m.label}
          {m.support !== "ok" ? (
            <span className="ml-1.5 rounded-sm border border-navy-600 px-1 text-[0.7rem] text-faint" title={m.supportNote}>
              {m.support === "limited" ? "Limited history" : "Insufficient history"}
            </span>
          ) : null}
        </div>
        <div className="text-right md:text-left">
          <span className="font-display text-[1.05rem] font-600 text-model" title="Median">{fmtStat(m.median)}</span>
          <span className="ml-1.5 text-xs text-mute">
            mean {fmtStat(m.mean)}, sd {fmtStat(m.sd)}, 80%: {fmtStat(m.range80[0])}–{fmtStat(m.range80[1])}
          </span>
        </div>
        {h ? (
          <>
            <div className="text-sm text-mute md:text-ink">{lineText(h)}</div>
            <div className="text-right md:text-left">
              <span className="font-display text-[1.05rem] font-600 text-model">{formatPct(h.modelProb)}</span>
              <span className="ml-1 text-xs text-faint md:hidden">model</span>
            </div>
            <div><MarketCell l={h} /></div>
            <div className="text-right md:text-left"><Edge l={h} /></div>
          </>
        ) : null}
      </div>
      {others.length ? (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-xs text-faint hover:text-mute">{others.length} more line{others.length > 1 ? "s" : ""}</summary>
          <ul className="mt-1.5 space-y-1">
            {others.map((l) => (
              <li key={`${l.op}${l.threshold}${l.variant}`} className="grid grid-cols-2 gap-x-3 text-sm md:grid-cols-[1.3fr_1.1fr_0.8fr_0.6fr_1fr_1.6fr]">
                <span className="hidden md:block" />
                <span className="hidden md:block" />
                <span className="text-mute">{lineText(l)}</span>
                <span className="text-right text-model md:text-left">{formatPct(l.modelProb)}</span>
                <span><MarketCell l={l} /></span>
                <span className="text-right md:text-left"><Edge l={l} /></span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function PlayerCard({ p }: { p: PropPlayerView }) {
  return (
    <div className="rounded-md border border-navy-700 bg-navy-900/60 px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h4 className="font-display text-lg font-600 text-ink">{p.name}</h4>
        <span className="text-sm text-mute">{p.position}, {p.team} vs {p.opp}</span>
        {p.injuryStatus ? <span className="rounded-sm bg-edge/15 px-1.5 py-0.5 text-xs text-edge">{p.injuryStatus}</span> : null}
      </div>
      <div className="mt-1 hidden grid-cols-[1.3fr_1.1fr_0.8fr_0.6fr_1fr_1.6fr] gap-x-3 text-[0.72rem] text-faint md:grid">
        <span>Market</span><span>Projection (median)</span><span>Line</span><span>Model</span><span>Exchange (mid)</span><span>Edge after fees</span>
      </div>
      <div className="mt-1">
        {p.markets.map((m) => <MarketRow key={m.key} m={m} />)}
      </div>
      {!isLocked(p.inputs) ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-faint hover:text-mute">Model inputs</summary>
          <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {Object.entries(p.inputs).filter(([, v]) => v !== null).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <dt className="text-faint">{k.replaceAll("_", " ")}</dt>
                <dd className="text-mute">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}

export async function PropBoard({ league, game }: { league: League; game?: string }) {
  const viewer = await getViewer();
  const res = await getProps(league, viewer.tier, game);
  if (!res.ok) {
    return <Unavailable title={`${league.toUpperCase()} player props unavailable`} body={res.reason} />;
  }
  const bt = res.backtest;
  const providers = res.markets.filter((m) => m.provider !== "manual" || m.quotes > 0);
  return (
    <div className="space-y-4">
      <Panel className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <SourceStamp>Model {res.model.version}, {res.model.status}</SourceStamp>
          <SourceStamp>Run {formatTimestamp(res.generatedAt)}</SourceStamp>
          {providers.length ? (
            providers.map((m) => (
              <SourceStamp key={m.provider}>
                {providerName(m.provider)}: {m.quotes} prices{m.last_captured_at ? `, ${formatTimestamp(m.last_captured_at)}` : ""}
              </SourceStamp>
            ))
          ) : (
            <SourceStamp>No exchange prices connected</SourceStamp>
          )}
        </div>
        {bt?.overall_vs_baseline ? (
          <p className="mt-2 text-sm leading-relaxed text-mute">
            Tested on {bt.test_seasons.join(", ")} ({bt.thresholds.toLocaleString()} thresholds, never used for tuning): log loss{" "}
            <span className="text-model">{bt.overall_vs_baseline.model.log_loss.toFixed(3)}</span> vs{" "}
            {bt.overall_vs_baseline.baseline.log_loss.toFixed(3)} for each player&apos;s recent hit rate (lower is better). No claim is
            made that these probabilities beat exchange prices; that needs stored price history.
          </p>
        ) : null}
        <p className="mt-1 text-xs text-faint">
          Edges use the ask, after the exchange fee, and only from prices captured in the last {res.rules.max_age_min} minutes with a
          spread under {(res.rules.max_spread * 100).toFixed(0)}¢. Anything else shows why it was left out.
        </p>
      </Panel>
      {isLocked(res.game) ? (
        <LockedPanel
          requires={res.game.requires}
          title="Player props are part of Plus"
          body={`Projections, probabilities and exchange comparisons for ${res.gameCount} upcoming games.`}
        />
      ) : !res.game ? (
        <Unavailable title="No upcoming games" body="There are no games in the projection window." />
      ) : (
        <>
          <nav aria-label="Games" className="flex flex-wrap gap-2">
            {res.schedule.map((s) => {
              const on = res.game && !isLocked(res.game) && s.id === res.game.id;
              return (
                <Link
                  key={s.id}
                  href={`/props?${league}=${encodeURIComponent(s.id)}#${league}`}
                  scroll={false}
                  aria-current={on ? "page" : undefined}
                  className={`rounded-full border px-3 py-1.5 text-sm ${on ? "border-model bg-model/15 text-ink" : "border-navy-600 text-mute hover:text-ink"}`}
                >
                  {s.away} at {s.home}
                </Link>
              );
            })}
          </nav>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-display text-2xl font-600 text-ink">{res.game.away.abbr} at {res.game.home.abbr}</h3>
            <span className="text-sm text-mute">{formatKickoff(res.game.startTime)}</span>
          </div>
          <div className="space-y-3">
            {[...res.game.players]
              .sort((a, b) => a.team.localeCompare(b.team) || (POS_ORDER[a.position] ?? 9) - (POS_ORDER[b.position] ?? 9))
              .map((p) => <PlayerCard key={p.id} p={p} />)}
          </div>
        </>
      )}
    </div>
  );
}
