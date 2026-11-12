import Link from "next/link";
import { formatKickoff, formatPct, formatTimestamp } from "@/lib/format";
import { providerName } from "@/lib/providers";
import { contractProbs, getExplorer, lineKey, marketMid, observedAt, SORTS, staleLine, seasonLabel, type ContractDetail, type ContributionView, type Explorer, type ExplorerGame, type ExplorerQuery, type ExplorerRow } from "@/server/data/explorer";
import { lineText, preferredOutcome, type LineProbs } from "@/lib/propOutcome";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import type { PropLineView } from "@/types/props";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell, LockedPanel, Unavailable } from "@/components/ui/primitives";
import { AutoSubmit } from "@/components/props/AutoSubmit";
import { age, cents, EdgeTag, flagText, fmt, lineLabel, PROVIDERS, quoteBy } from "./bits";
import { Contributions, DistributionChart, lineProvider, MarketBox, ModelBox, OutcomeBar, PreferredBlock, type PreferredView } from "./PropParts";
import { DataSection, InjurySection, MatchupSection, OpportunitySection, Section } from "./AnalysisSections";
import { HistoryTabs, type HistoryTabsData } from "./HistoryTabs";
import { FavoritesScope, FavoriteStar, RecentlyViewed, TrackView } from "./local";

// Player data history behind the projection (the engine's "support"), not a confidence that the projection beats the market.
const CONF = { ok: { label: "Full history", cls: "text-mute" }, limited: { label: "Limited data", cls: "text-edge" }, insufficient: { label: "Very limited data", cls: "text-edge" } } as const;

export function propsHref(league: League, q: ExplorerQuery, patch: Partial<ExplorerQuery>): string {
  const all = { ...q, ...patch };
  const p = new URLSearchParams({ sport: league });
  for (const [k, v] of Object.entries(all)) if (v) p.set(k, String(v));
  return `/props?${p.toString()}`;
}

function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

const time = (g: ExplorerGame) => (g.status === "started" ? "Started" : formatKickoff(g.startTime).split(", ").slice(-1)[0]);

// ------------------------------------------------------------------ game switching
function GameRail({ league, x }: { league: League; x: Extract<Explorer, { ok: true }> }) {
  const days = new Map<string, ExplorerGame[]>();
  for (const g of x.games) days.set(g.gameDate, [...(days.get(g.gameDate) ?? []), g]);
  return (
    <nav aria-label="Games" className="space-y-3">
      {[...days.entries()].map(([d, gs]) => (
        <div key={d}>
          <h3 className="px-2 pb-1 text-xs text-faint">{dayLabel(d)}</h3>
          <ul className="space-y-0.5">
            {gs.map((g) => {
              const on = g.id === x.game?.id && !x.searchAll;
              return (
                <li key={g.id}>
                  <Link
                    href={propsHref(league, { cat: x.query.cat, sort: x.query.sort, only: x.query.only }, { game: g.id })}
                    scroll={false}
                    aria-current={on ? "page" : undefined}
                    className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${on ? "bg-navy-800 text-ink ring-1 ring-model/40" : "text-mute hover:bg-navy-850 hover:text-ink"}`}
                  >
                    <TeamBadge league={league} abbr={g.away.abbr} size="sm" />
                    <span className="text-faint">@</span>
                    <TeamBadge league={league} abbr={g.home.abbr} size="sm" />
                    <span className="ml-auto font-mono text-[0.7rem] text-faint">{time(g)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function GameChips({ league, x }: { league: League; x: Extract<Explorer, { ok: true }> }) {
  return (
    <nav aria-label="Games" className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0 xl:hidden">
      {x.games.map((g) => {
        const on = g.id === x.game?.id && !x.searchAll;
        return (
          <Link
            key={g.id}
            href={propsHref(league, { cat: x.query.cat, sort: x.query.sort, only: x.query.only, date: x.query.date }, { game: g.id })}
            scroll={false}
            aria-current={on ? "page" : undefined}
            className={`flex shrink-0 items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 ${on ? "border-model bg-model/15" : "border-navy-700 bg-navy-900 hover:border-navy-600"}`}
          >
            <TeamBadge league={league} abbr={g.away.abbr} size="sm" />
            <TeamBadge league={league} abbr={g.home.abbr} size="sm" />
            <span className={`font-mono text-[0.68rem] ${on ? "text-ink" : "text-faint"}`}>{x.games.some((o) => o.gameDate !== g.gameDate) ? `${dayLabel(g.gameDate).split(", ")[0]} ` : ""}{time(g)}</span>
          </Link>
        );
      })}
    </nav>
  );
}

// ------------------------------------------------------------------ player cards
/** A model threshold (no market quote) as a small pill: "20+ 62%". Always labelled as the model's ladder. */
function LadderPill({ l, href, active }: { l: PropLineView; href: string; active: boolean }) {
  return (
    <Link
      href={href}
      scroll={false}
      aria-current={active ? "true" : undefined}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${active ? "border-model bg-model/15" : "border-navy-700 bg-navy-900 hover:border-navy-600"}`}
    >
      <span className="font-mono text-mute">{lineLabel(l)}</span>
      <span className="font-mono text-model">{formatPct(l.modelProb)}</span>
    </Link>
  );
}

/** Other quoted contracts for the player (beyond the main market line): line, model %, market %. */
function QuotedPill({ l, href, active }: { l: PropLineView; href: string; active: boolean }) {
  const mid = marketMid(l);
  return (
    <Link href={href} scroll={false} aria-current={active ? "true" : undefined}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${active ? "border-model bg-model/15" : "border-navy-600 bg-navy-900 hover:border-navy-500"}`}>
      <span className="font-mono text-ink">{lineLabel(l)}</span>
      <span className="font-mono text-model">{formatPct(l.modelProb)}</span>
      {mid != null ? <span className="font-mono text-market">{formatPct(mid)}</span> : null}
      {l.edge ? <span className="h-1.5 w-1.5 rounded-full bg-edge" aria-label="edge" /> : null}
    </Link>
  );
}

const SIDE = (p: PreferredView, line: number | null) =>
  p.kind === "side" ? `${p.side === "over" ? "Over" : "Under"}${line != null ? ` ${lineText(line)}` : ""}` : p.kind === "close" ? "Too close to call" : "No preference";

function PlayerRow({ r, league, q, activeKey }: { r: ExplorerRow; league: League; q: ExplorerQuery; activeKey: string | null }) {
  const c = CONF[r.support];
  const main = r.headline;
  const cardKey = main ? lineKey(r.id, main) : `${r.id}~card`;
  const href = propsHref(league, { ...q, game: q.game ?? r.gameId }, { line: cardKey });
  const on = activeKey != null && activeKey.split("~")[0] === r.id;
  const stale = main ? staleLine(main) : false;
  const prov = main ? lineProvider(main) : null;
  const inj = r.injury?.status && r.injury.status !== "available" ? (r.injury.lateScratch ? "Late scratch" : r.injury.rawStatus ?? r.injury.status) : !r.injury && r.injuryStatus ? r.injuryStatus : null;
  return (
    <li data-fav-id={`${league}:${r.id}`} className="flex items-stretch gap-1">
      <div className="flex items-center"><FavoriteStar id={`${league}:${r.id}`} name={r.name} /></div>
      <Link href={href} scroll={false} aria-current={on ? "true" : undefined}
        className={`grid min-w-0 flex-1 grid-cols-3 items-center gap-x-3 gap-y-2 rounded-lg border px-3 py-2.5 @xl:grid-cols-[minmax(8rem,1.6fr)_4.5rem_4.5rem_minmax(6.5rem,1.2fr)_minmax(7rem,1fr)] ${on ? "border-model/70 bg-navy-800" : "border-transparent bg-navy-900 hover:bg-navy-850"}`}>
        <span className="col-span-3 flex min-w-0 items-center gap-2 @xl:col-span-1">
          <TeamBadge league={league} abbr={r.team} size="sm" />
          <span className="min-w-0">
            <span className="block truncate font-600 text-ink">{r.name}</span>
            <span className="block truncate text-[0.72rem] text-faint">
              {r.position} · {r.team === r.matchup.split(" @ ")[1] ? `vs ${r.opp}` : `@ ${r.opp}`}
              {inj ? <span className="text-edge"> · {inj}{r.injury && !r.injury.confirmed ? "*" : ""}</span> : null}
              {r.changes ? <span> · updated for injury news</span> : null}
            </span>
          </span>
        </span>
        <span className="min-w-0">
          <span className={`block font-mono leading-tight ${main ? "text-lg text-market" : "text-sm text-faint"}`}>{main && r.atLine ? lineText(r.atLine.line) : "No line"}</span>
          <span className={`block truncate text-[0.68rem] ${stale ? "text-edge" : "text-faint"}`}>{main ? (stale ? "may have moved" : prov ?? "Market") : "none listed"}</span>
        </span>
        <span className="min-w-0">
          <span className="block font-mono text-lg leading-tight text-model">{r.mean.toFixed(1)}</span>
          <span className="block text-[0.68rem] text-faint">model avg</span>
        </span>
        <span className="min-w-0">
          {r.atLine ? (
            <>
              <span className="flex h-1.5 overflow-hidden rounded-full bg-navy-600" aria-hidden="true"><span className="bg-model" style={{ width: `${r.atLine.over * 100}%` }} /></span>
              <span className="mt-1 flex justify-between text-[0.7rem]"><span className="text-ink">O {formatPct(r.atLine.over)}</span><span className="text-mute">U {formatPct(r.atLine.under)}</span></span>
            </>
          ) : <span className="text-[0.7rem] text-faint">Needs a market line</span>}
        </span>
        <span className="col-span-3 flex min-w-0 items-baseline justify-between gap-2 @xl:col-span-1 @xl:block">
          <span className={`block truncate text-[0.8rem] ${r.preferred.kind === "side" ? "font-600 text-ink" : "text-mute"}`}>
            {r.preferred.kind === "side" ? `${SIDE(r.preferred, r.atLine?.line ?? null)} · ${formatPct(r.preferred.prob)}` : r.preferred.kind === "close" ? "Too close to call" : main ? "No preference" : "–"}
            {main?.edge ? <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-edge align-middle" title="Model-implied +EV after fees (unverified)" aria-label="Model-implied +EV (unverified)" /> : null}
          </span>
          <span className={`block text-[0.68rem] ${c.cls}`}>{c.label}</span>
        </span>
      </Link>
    </li>
  );
}

// ------------------------------------------------------------------ detail
function MarketQuotes({ l, x }: { l: PropLineView; x: Extract<Explorer, { ok: true }> }) {
  const qb = quoteBy(l);
  return (
    <table className="w-full text-xs">
      <thead className="text-faint"><tr><th className="py-1 text-left font-500">Exchange</th><th className="text-right font-500">Bid/Ask</th><th className="text-right font-500">Implied</th><th className="text-right font-500">Size</th><th className="text-right font-500">Seen</th></tr></thead>
      <tbody>
        {PROVIDERS.map((p) => {
          const qq = qb[p];
          return (
            <tr key={p} className="border-t border-navy-700/70">
              <td className="py-1.5 text-ink">{providerName(p)}</td>
              {qq ? (
                <>
                  <td className={`text-right font-mono ${qq.usable ? "text-market" : "text-faint line-through"}`}>{cents(qq.bid)}/{cents(qq.ask)}¢</td>
                  <td className={`text-right font-mono ${qq.usable ? "text-market" : "text-faint"}`}>{qq.mid != null ? formatPct(qq.mid) : "–"}</td>
                  <td className="text-right font-mono text-mute">{qq.askSize != null ? Math.round(qq.askSize) : "n/a"}</td>
                  <td className="text-right font-mono text-faint">{qq.usable ? age(qq.capturedAt, x.now) : flagText(qq.flags)}</td>
                </>
              ) : (
                <td colSpan={4} className="text-right text-faint">Not listed</td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Short names for recorded adjustment steps, for the one-line reason. */
const STEP: Record<string, string> = {
  minutes: "minutes", blowout: "blowout risk", usage: "teammates out", pace: "pace", matchup: "matchup",
  game_environment: "team volume", opportunity: "snap-share trend", matchup_share: "opponent's target share allowed",
  lineup: "lineup", matchup_efficiency: "opponent's efficiency allowed", other: "QB adjustment",
};

const NO_PREF: Record<string, string> = {
  no_market_line: "No market lists this prop, so there is no line to prefer a side of.",
  insufficient_history: "Too little player history to prefer a side.",
  outside_range: "The line is outside the model's simulated range, so no side is preferred.",
  stale_line: "The market line is stale and may have moved, so no side is preferred.",
};

/** One short sentence: why the model lands on this side (or why it prefers neither). Reads only published numbers. */
function whyLine(p: PreferredView, pr: LineProbs | null, mean: number, c: ContributionView | null): string {
  if (p.kind === "close" && pr) return `Over ${formatPct(pr.over)} vs Under ${formatPct(pr.under)}: within 3 points of even, so no side is preferred.`;
  if (p.kind !== "side" || !pr) return NO_PREF[(p as { reason?: string }).reason ?? "no_market_line"] ?? NO_PREF.no_market_line;
  const side = p.side === "over" ? "above" : "below";
  let t = `Model Room gives a ${formatPct(p.prob)} chance he finishes ${side} ${lineText(pr.line)}; its average is ${mean.toFixed(1)}.`;
  if (p.againstAverage) t += ` The average sits on the other side because a few outlying games pull it; the chance at the line decides.`;
  const big = c?.steps?.filter((s) => s.key !== "baseline" && s.key !== "simulation" && Math.abs(s.value) >= 0.3).sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
  if (big) t += ` Largest recorded adjustment: ${STEP[big.key] ?? big.key.replaceAll("_", " ")} (${big.value > 0 ? "+" : "−"}${Math.abs(big.value).toFixed(1)}).`;
  return t;
}

function Detail({ d, league, x, explicit }: { d: ContractDetail; league: League; x: Extract<Explorer, { ok: true }>; explicit: boolean }) {
  const { row: r, line: sel } = d;
  const quoted = sel && sel.quotes.length ? sel : null;
  // The market line on the card: the selected quoted contract, else the player's main market line.
  const market = quoted ?? r.headline;
  const pr = quoted ? contractProbs(quoted) : r.atLine;
  const pref: PreferredView = quoted && quoted !== r.headline
    ? (staleLine(quoted) ? { kind: "none", reason: "stale_line" } : preferredOutcome(pr, { support: r.support, mean: r.mean }))
    : r.preferred;
  // A model threshold the reader picked (no market quote): shown as the model's, never as a market line.
  const ladderSel = sel && !sel.quotes.length ? sel : null;
  const markLine = market ? pr?.line ?? null : ladderSel ? (ladderSel.op === ">=" ? ladderSel.threshold - 0.5 : ladderSel.threshold) : null;
  const implied = market ? marketMid(market) : null;
  const closeHref = propsHref(league, { ...x.query }, { line: undefined });
  const title = `${r.name} ${x.category.label.toLowerCase()}`;
  const ms = d.marketStats;
  const contrib = isLocked(r.contributions) ? null : r.contributions;
  const stale = market ? staleLine(market) : false;
  const conf = CONF[r.support];
  const clearOn = ladderSel ?? market;
  const h = r.history;
  const seasonText = seasonLabel(league, h.boardSeason);
  const histData: HistoryTabsData = {
    stat: x.category.label,
    games: h.games,
    published: h.published,
    boardSeason: h.boardSeason,
    seasonText,
    season: h.season ? { games: h.season.games, avg: h.season.avg, opportunity: h.season.opportunity } : null,
    opportunity: h.opportunity,
    clear: clearOn ? { k: clearOn.threshold, op: clearOn.op === ">" ? ">" : ">=", label: ladderSel ? `${lineLabel(ladderSel)}` : `Over ${lineText(markLine ?? clearOn.threshold)}` } : null,
    seasonNames: Object.fromEntries([...new Set(h.games.map((g) => g.season).filter((s): s is number => s != null))].map((s) => [s, seasonLabel(league, s)])),
  };
  const played = h.games.filter((g) => g.value != null).slice(0, 5);
  const histSummary = played.length ? `last ${played.length}: ${fmt(played.reduce((a, g) => a + g.value!, 0) / played.length)} avg` : "no past games";
  const others = r.lines.filter((l) => l !== market && l.quotes.length);
  const hrefFor = (l: PropLineView) => propsHref(league, { ...x.query, game: x.query.game ?? r.gameId }, { line: lineKey(r.id, l) });
  const inj = r.injury?.status && r.injury.status !== "available" ? r.injury : null;
  return (
    <div key={d.key} className={explicit ? "fixed inset-0 z-50 overflow-y-auto overscroll-contain bg-navy-950 lg:static lg:z-auto lg:overflow-visible lg:bg-transparent" : "hidden lg:block"}>
      {explicit ? (
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-navy-700 bg-navy-950 px-3 py-1.5 lg:hidden">
          <Link href={closeHref} scroll={false} className="flex min-h-11 items-center gap-1 pr-2 text-sm font-500 text-model">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>
            Players
          </Link>
          <span className="ml-auto truncate text-xs text-faint">{r.matchup}{x.game ? ` · ${formatKickoff(x.game.startTime).split(", ").slice(-1)[0]}` : ""}</span>
        </div>
      ) : null}
      <aside aria-label="Player analysis" className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:overscroll-contain">
        <TrackView item={{ href: propsHref(league, { game: r.gameId, cat: x.category.key }, { line: d.key }), label: title, sub: `${r.matchup} · ${league.toUpperCase()}` }} />
        <div className="space-y-4 p-4 lg:rounded-xl lg:bg-navy-900 lg:p-5">
          <div className="flex items-start gap-2.5">
            <TeamBadge league={league} abbr={r.team} />
            <div className="min-w-0 flex-1">
              <h2 className="font-display text-2xl font-700 leading-tight text-ink">{r.name}</h2>
              <p className="text-xs text-mute">{r.position} · {r.matchup} · {x.category.label}</p>
            </div>
            <span className={`shrink-0 rounded-full bg-navy-850 px-2.5 py-1 text-[0.7rem] ${conf.cls}`} title={r.supportNote}>{conf.label}</span>
            <FavoriteStar id={`${league}:${r.id}`} name={r.name} />
          </div>
          {inj ? (
            <p className="-mt-2 text-xs text-edge">{inj.lateScratch ? "Late scratch: " : ""}{inj.rawStatus ?? inj.status} · {inj.confirmed ? "official report" : "reported, not yet official"}</p>
          ) : null}

          <div className="grid grid-cols-2 gap-2.5">
            <MarketBox l={market} observed={market ? observedAt(market) : null} now={x.now} stale={stale} />
            <ModelBox mean={r.mean} median={r.median} range80={r.range80} supportLabel="" supportCls="" />
          </div>

          {pr && market ? (
            <div>
              <OutcomeBar pr={pr} l={market} compact />
              <p className="mt-0.5 text-[0.68rem] text-faint">Model Room&apos;s chance at {lineText(pr.line)}{pr.push ? `; push ${formatPct(pr.push)}` : ""}.</p>
            </div>
          ) : null}
          {ladderSel ? (
            <p className="rounded-md bg-navy-850 px-3 py-2 text-xs text-mute">
              Model threshold, not a market line: Model Room gives <span className="text-model">{formatPct(ladderSel.modelProb)}</span> to {lineLabel(ladderSel)} {x.category.label.toLowerCase()}.
            </p>
          ) : null}

          <section aria-label="Preferred outcome" className="rounded-lg bg-navy-850 px-3.5 py-3">
            <p className="font-display text-xl font-700 text-ink">
              {pref.kind === "side" && pr ? `${pref.side === "over" ? "Over" : "Under"} ${lineText(pr.line)} · ${formatPct(pref.prob)}` : pref.kind === "close" ? "Too close to call" : "No preferred outcome"}
            </p>
            <p className="mt-1 text-[0.8rem] leading-relaxed text-mute">{whyLine(pref, pr, r.mean, contrib)}</p>
          </section>

          <div>
            <Section title="Recent performance" summary={histSummary}>
              <HistoryTabs d={histData} />
            </Section>
            <InjurySection league={league} r={r} feed={x.injuries} feedAt={x.injuryFeedAt} />
            <OpportunitySection league={league} r={r} contributions={contrib} />
            <MatchupSection league={league} r={r} cat={x.category.key} contributions={contrib} />
            <Section title="Model explanation" summary={contrib?.steps ? `${contrib.steps.length} recorded steps` : isLocked(r.contributions) ? "Pro" : "final only"}>
              <div className="space-y-1.5">
                <h4 className="text-[0.68rem] text-faint">From his usual production to the projected average</h4>
                {isLocked(r.contributions) ? (
                  <div className="flex items-center gap-2 text-faint"><span>The model&apos;s step-by-step record is part of Pro.</span><LockedCell requires={r.contributions.requires} /></div>
                ) : (
                  <Contributions c={r.contributions} league={league} />
                )}
              </div>
              {r.grid ? <DistributionChart grid={r.grid} line={markLine} label={x.category.label.toLowerCase()} /> : null}
              {pr && market ? <OutcomeBar pr={pr} l={market} /> : null}
              {market ? <PreferredBlock p={pref} pr={pr} mean={r.mean} /> : null}
              <p>Average {fmt(r.mean)} · middle outcome {fmt(r.median)} · typical range {fmt(r.range80[0])}–{fmt(r.range80[1])} (80% of simulated games).</p>
              {ms ? (
                <p>
                  How this category tested: {ms.n.toLocaleString()} {x.category.label.toLowerCase()} thresholds in held-out seasons, log loss {ms.log_loss.toFixed(3)}
                  {ms.baseline_log_loss != null ? ` vs ${ms.baseline_log_loss.toFixed(3)} for recent form` : ""}
                  {ms.ece != null ? `, calibration error ${(ms.ece * 100).toFixed(1)}%` : ""}.{" "}
                  <Link href={`/performance/props?sport=${league}&cat=${x.category.key}`} className="text-model hover:underline">Validation by category</Link>
                </p>
              ) : null}
              <div>
                <h4 className="mb-1 text-[0.68rem] text-faint">All model inputs</h4>
                {isLocked(r.inputs) ? (
                  <div className="flex items-center gap-2 text-faint"><span>Model inputs (usage, matchup factors) are part of Pro.</span><LockedCell requires={r.inputs.requires} /></div>
                ) : (
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                    {Object.entries(r.inputs).filter(([, v]) => v !== null && typeof v !== "object").map(([kk, v]) => (
                      <div key={kk} className="flex justify-between gap-2"><dt className="text-faint">{kk.replaceAll("_", " ")}</dt><dd className="font-mono text-mute">{String(v)}</dd></div>
                    ))}
                  </dl>
                )}
              </div>
            </Section>
            <Section title="Market prices & other lines" summary={market ? `${lineProvider(market) ?? "Market"}${others.length ? ` · ${others.length + 1} lines` : ""}` : r.ladder.length ? "no market line · model ladder" : "no market line"} warn={stale}>
              {market ? (
                <>
                  <MarketQuotes l={market} x={x} />
                  {implied != null ? <p className="text-faint">Market-implied chance of Yes (bid/ask midpoint): {formatPct(implied)}{market.market ? "" : " (wide or thin quote, for reference only)"}.</p> : null}
                </>
              ) : <p>No market lists this prop. Model Room does not borrow a line from another provider or invent one.</p>}
              {market?.edge ? (
                <div className="rounded-md bg-navy-850 p-2.5">
                  <div className="flex items-center justify-between"><span className="font-600 text-edge">Model-implied expected value (unverified)</span><EdgeTag l={market} /></div>
                  <p className="mt-1">
                    {market.edge.side === "yes" ? "Yes" : "No"} at {cents(market.edge.price)}¢ on {providerName(market.edge.provider)}. Model chance − price − fee ={" "}
                    <span className="text-edge">+{(market.edge.ev * 100).toFixed(1)}¢</span> per $1 contract.{market.edge.grade !== "strong" ? ` Data warnings: ${market.edge.reasons.join("; ")}.` : ""} This assumes the model&apos;s probability is right; it is not a verified edge.
                  </p>
                </div>
              ) : null}
              {others.length ? (
                <div>
                  <h4 className="mb-1 text-[0.68rem] text-faint">Other quoted lines (line · model · market)</h4>
                  <div className="flex flex-wrap gap-1.5">{others.map((l) => { const k = lineKey(r.id, l); return <QuotedPill key={k} l={l} href={hrefFor(l)} active={k === d.key} />; })}</div>
                </div>
              ) : null}
              {r.ladder.length ? (
                <div>
                  <h4 className="mb-1 text-[0.68rem] text-faint">Model ladder (Model Room&apos;s own thresholds, not market lines)</h4>
                  <div className="flex flex-wrap gap-1.5">{r.ladder.map((l) => { const k = lineKey(r.id, l); return <LadderPill key={k} l={l} href={hrefFor(l)} active={k === d.key} />; })}</div>
                </div>
              ) : null}
            </Section>
            <DataSection league={league} version={x.model.version} generatedAt={x.generatedAt} feedAt={x.injuryFeedAt} lineSeen={market ? observedAt(market) : null} lineStale={stale}
              now={x.now} support={conf.label} supportNote={r.supportNote} history={h} seasonText={seasonText} />
          </div>
          <p className="text-[0.65rem] text-faint">Not a betting recommendation. Prop probabilities have not been validated against market prices.</p>
        </div>
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ page
export async function Marketplace({ league, query }: { league: League; query: ExplorerQuery }) {
  const viewer = await getViewer();
  const x = await getExplorer(league, viewer.tier, query);
  if (!x.ok) return <Unavailable title={`${league.toUpperCase()} player props unavailable`} body={x.reason} />;
  if (!x.games.length) {
    return <Unavailable title="No games with props that day" body="Pick another day, or All upcoming." />;
  }
  const game = x.game;
  const rows = x.rows;
  const explicit = Boolean(query.line);
  const first = !isLocked(rows) && rows.length ? rows[0] : null;
  const detail: ContractDetail | null = !isLocked(x.detail) && x.detail ? x.detail
    : first ? { row: first, line: first.headline, key: first.headline ? lineKey(first.id, first.headline) : `${first.id}~card`, marketStats: x.backtest?.by_market?.[x.category.key] ?? null }
    : null;
  const activeKey = explicit ? query.line ?? null : detail?.key ?? null;
  const sel = "rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm text-ink";

  const statLabel = x.category.label.toLowerCase();

  return (
    <div className="space-y-3">
      {x.live ? (
        <details data-live data-found={x.live.found} data-matched={x.live.matched} className="group rounded-md border border-navy-700 bg-navy-900 px-3 py-2 text-xs">
          <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
            <span className="h-2 w-2 shrink-0 rounded-full bg-good" aria-hidden="true" />
            <span className="font-600 text-ink">Owner view · live Polymarket US prices</span>
            <span className="hidden text-faint sm:inline">· {formatTimestamp(x.live.fetchedAt)} · {x.live.matched} lines</span>
            <span className="ml-auto text-faint group-open:hidden">About</span>
          </summary>
          <p className="mt-1.5 text-mute">
            Fetched {formatTimestamp(x.live.fetchedAt)} for {x.live.games === 1 ? "this game" : `${x.live.games} games`}: {x.live.found} found on Polymarket, {x.live.matched} lines matched.
            Only your test-site login sees these; nothing is stored, and production never shows them. Contract sizes aren&apos;t in the listing, and the model&apos;s prop probabilities haven&apos;t been validated against these prices, so expected values are unverified estimates.
          </p>
        </details>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_25rem] xl:grid-cols-[12rem_minmax(0,1fr)_28rem]">
        <div className="hidden space-y-5 xl:block">
          <GameRail league={league} x={x} />
          <div>
            <h3 className="px-2 pb-1 text-xs text-faint">Recently viewed</h3>
            <RecentlyViewed />
          </div>
        </div>

        <div className="min-w-0 space-y-3">
          <GameChips league={league} x={x} />

          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            {x.searchAll ? (
              <h2 className="font-display text-lg font-600 text-ink">“{query.q}” across every {league.toUpperCase()} game</h2>
            ) : game ? (
              <h2 className="font-display text-lg font-600 text-ink sm:text-xl">
                <span className="sm:hidden">{game.away.abbr} @ {game.home.abbr}</span>
                <span className="hidden sm:inline">{game.away.name} <span className="text-faint">at</span> {game.home.name}</span>
                <span className="ml-2 font-sans text-sm font-400 text-mute">{formatKickoff(game.startTime)}</span>
              </h2>
            ) : null}
            <span className="hidden items-center gap-3 text-[0.7rem] text-mute md:flex">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-market" />Market line (as listed)</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-model" />Model Room projection</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-edge" />Model-implied +EV after fees (unverified)</span>
            </span>
          </div>

          <nav aria-label="Prop categories" className="-mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            {x.categories.map((c) => {
              const on = c.key === x.category.key;
              return (
                <Link key={c.key} href={propsHref(league, { ...x.query, line: undefined }, { cat: c.key })} scroll={false} aria-current={on ? "page" : undefined}
                  className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-500 ${on ? "bg-ink text-navy-950" : "bg-navy-850 text-mute hover:text-ink"}`}>
                  {c.label}
                </Link>
              );
            })}
          </nav>

          {league === "nfl" && x.category.key.startsWith("passing") ? (
            <p className="rounded-md border border-navy-700 px-3 py-2 text-xs text-mute">
              Less reliable market: in 2023–25 tests the model&apos;s range for QB passing yards was about 40% wider than real outcomes, and at the
              median line it expected the over 45% of the time when it happened 54% of the time. Treat these probabilities with extra caution.
            </p>
          ) : null}

          <form action="/props" className="flex flex-wrap items-center gap-2">
            <input type="hidden" name="sport" value={league} />
            {query.game ? <input type="hidden" name="game" value={query.game} /> : null}
            {query.date ? <input type="hidden" name="date" value={query.date} /> : null}
            <input type="hidden" name="cat" value={x.category.key} />
            <label className="sr-only" htmlFor="q">Search players or teams</label>
            <input id="q" name="q" type="search" enterKeyHint="search" defaultValue={x.query.q ?? ""} placeholder="Search players or teams" className={`${sel} w-full sm:w-auto sm:min-w-56 sm:flex-1 lg:max-w-xs`} />
            {game && !x.searchAll ? (
              <select name="team" aria-label="Team" defaultValue={x.query.team ?? ""} className={`${sel} min-w-0 flex-1 text-[0.8rem] sm:flex-none sm:text-sm`}>
                <option value="">Both teams</option>
                <option value={game.away.abbr}>{game.away.abbr}</option>
                <option value={game.home.abbr}>{game.home.abbr}</option>
              </select>
            ) : null}
            <select name="only" aria-label="Show" defaultValue={x.query.only ?? ""} className={`${sel} min-w-0 flex-1 text-[0.8rem] sm:flex-none sm:text-sm`}>
              <option value="">All players</option>
              <option value="priced">With market prices</option>
              <option value="edges">Model-implied +EV (unverified)</option>
              <option value="strong">+EV with no data warnings</option>
              <option value="ok">Full player history</option>
            </select>
            <select name="sort" aria-label="Sort" defaultValue={x.sort} className={`${sel} min-w-0 flex-1 text-[0.8rem] sm:flex-none sm:text-sm`}>
              {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <button type="submit" className="sr-only">Search</button>
            {x.query.q ? <Link href={propsHref(league, { cat: x.query.cat, game: query.game, date: query.date }, {})} className="text-sm text-mute hover:text-ink">Clear search</Link> : null}
            <AutoSubmit />
          </form>

          {isLocked(rows) ? (
            <LockedPanel requires={rows.requires} title="Player props are part of Plus" body={`Every player's projection, probabilities and exchange comparison for ${x.games.length} upcoming games.`} />
          ) : rows.length === 0 ? (
            <p className="px-1 py-6 text-center text-sm text-mute">
              {x.totalPlayers ? "No players match. Try another search or filter." : `No ${statLabel} projections for this game.`}
            </p>
          ) : (
            <FavoritesScope>
              <div className="@container">
              <div className="mb-1 hidden grid-cols-[minmax(8rem,1.6fr)_4.5rem_4.5rem_minmax(6.5rem,1.2fr)_minmax(7rem,1fr)] gap-x-3 pl-9 pr-3 text-[0.68rem] text-faint @xl:grid">
                <span>Player</span><span className="text-market">Market line</span><span className="text-model">Model Room</span><span>Model chance</span><span>Preferred · history</span>
              </div>
              <ul className="space-y-1.5">{rows.map((r) => <PlayerRow key={`${r.gameId}:${r.id}`} r={r} league={league} q={x.query} activeKey={activeKey} />)}</ul>
              </div>
            </FavoritesScope>
          )}
        </div>

        <div>
          {isLocked(x.detail) ? (
            <div className={explicit ? "" : "hidden lg:block"}><LockedPanel requires={x.detail.requires} title="Contract details are part of Plus" body="Model probability, exchange quotes, edge and recent games for every line." /></div>
          ) : detail ? (
            <Detail d={detail} league={league} x={x} explicit={explicit} />
          ) : (
            <p className="hidden text-sm text-faint lg:block">Pick a line to see the details.</p>
          )}
        </div>
      </div>

      <p className="text-xs leading-relaxed text-faint">
        Market-implied probability is the midpoint of an exchange&apos;s bid and ask. Model-implied expected value (unverified) uses the price you would actually pay (the ask) after the exchange fee,
        from quotes under {x.rules.max_age_min} minutes old with a spread under {(x.rules.max_spread * 100).toFixed(0)}¢. Struck-through prices are stale,
        thin or one-sided and are never used. The model&apos;s probability is its projection; it has not yet been validated against market prices, so
        a positive expected value is an estimate, not a verified edge. Data history labels describe how much of a player&apos;s history the projection rests on, not how likely it is to be right.
      </p>
    </div>
  );
}
