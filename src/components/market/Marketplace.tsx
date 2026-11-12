import Link from "next/link";
import { Confirmed, sourceLabel } from "@/components/injuries/InjuryFlags";
import { formatKickoff, formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { providerName } from "@/lib/providers";
import { contractProbs, getExplorer, lineKey, marketMid, observedAt, SORTS, staleLine, type ContractDetail, type Explorer, type ExplorerGame, type ExplorerQuery, type ExplorerRow } from "@/server/data/explorer";
import { preferredOutcome } from "@/lib/propOutcome";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import type { PropLineView } from "@/types/props";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell, LockedPanel, Unavailable } from "@/components/ui/primitives";
import { AutoSubmit } from "@/components/props/AutoSubmit";
import { age, cents, EdgeTag, flagText, lineLabel, PROVIDERS, quoteBy } from "./bits";
import { Contributions, DistributionChart, InjuriesFreshness, MarketBox, ModelBox, OutcomeBar, PreferredBlock, PreferredChip, type PreferredView } from "./PropParts";
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

function AvailabilityPanel({ r }: { r: ExplorerRow }) {
  const i = r.injury;
  if (!i && !r.teammatesOut.length && !r.changes) return null;
  return (
    <section aria-label="Availability" className="space-y-1 rounded-md border border-navy-700 p-2.5 text-xs">
      <h3 className="text-[0.65rem] font-600 uppercase tracking-wider text-faint">Availability</h3>
      {i?.status ? (
        <p className="text-mute">
          <span className={i.status === "available" ? "text-good" : "text-edge"}>{i.lateScratch ? "Late scratch: " : ""}{i.rawStatus ?? i.status}</span>
          {" "}· <Confirmed confirmed={i.confirmed} /> · {sourceLabel(i.source)}{i.reportTime ? `, ${formatTimestamp(i.reportTime)}` : ""}
          {i.starterConfirmed != null ? ` · ${i.starterConfirmed ? "confirmed starter" : "not in the confirmed starting five"}` : ""}
        </p>
      ) : i ? <p className="text-faint">Not on the injury report.</p> : null}
      {i?.conflict ? <p className="text-edge">Sources disagree: {i.conflict}. The official designation is used.</p> : null}
      {i?.startingQb ? <p className="text-mute">Projected starting QB: <span className="text-ink">{i.startingQb}</span></p> : null}
      {i?.notes.map((n) => <p key={n} className="text-mute">{n}</p>)}
      {r.teammatesOut.length ? (
        <p className="text-mute">Teammates out: {r.teammatesOut.map((t) => `${t.name}${t.position ? ` (${t.position})` : ""}${t.status && t.status !== "out" ? `, ${t.status}` : ""}`).join("; ")}</p>
      ) : null}
      {r.changes ? (
        <p className="text-edge">
          Updated for injury news{r.changes.previous_at ? ` since ${formatTimestamp(r.changes.previous_at)}` : ""}: {r.changes.reasons.join("; ")}.{" "}
          <span className="text-mute">{r.changes.markets.map((m) => `${m.label} ${m.from} → ${m.to}`).join(", ")}</span>
        </p>
      ) : null}
    </section>
  );
}

function PlayerRow({ r, league, q, activeKey, now }: { r: ExplorerRow; league: League; q: ExplorerQuery; activeKey: string | null; now: number }) {
  const c = CONF[r.support];
  const href = (l: PropLineView | null) => propsHref(league, { ...q, game: q.game ?? r.gameId }, { line: l ? lineKey(r.id, l) : `${r.id}~card` });
  const main = r.headline;
  const quotedOthers = r.lines.filter((l) => l !== main && l.quotes.length);
  const cardKey = main ? lineKey(r.id, main) : `${r.id}~card`;
  return (
    <li data-fav-id={`${league}:${r.id}`} className="rounded-lg border border-navy-700 bg-navy-900 p-3">
      <div className="flex items-center gap-2">
        <FavoriteStar id={`${league}:${r.id}`} name={r.name} />
        <TeamBadge league={league} abbr={r.team} size="sm" />
        <div className="min-w-0 flex-1">
          <Link href={href(main)} scroll={false} className="block truncate font-600 text-ink hover:underline">{r.name}</Link>
          <div className="flex flex-wrap gap-x-2 text-[0.72rem] text-faint">
            <span>{r.position} · {r.team === r.matchup.split(" @ ")[1] ? `vs ${r.opp}` : `@ ${r.opp}`}</span>
            {r.injury?.status && r.injury.status !== "available" ? (
              <span className="text-edge" title={`${sourceLabel(r.injury.source)}${r.injury.reportTime ? `, ${formatTimestamp(r.injury.reportTime)}` : ""}${r.injury.confirmed ? " (official)" : " (report)"}`}>
                {r.injury.lateScratch ? "Late scratch" : r.injury.rawStatus ?? r.injury.status}{r.injury.confirmed ? "" : "*"}
              </span>
            ) : r.injuryStatus && !r.injury ? <span className="text-edge">{r.injuryStatus}</span> : null}
            {r.changes ? <span className="font-600 text-edge" title={r.changes.reasons.join("; ")}>Updated: injury news</span> : null}
          </div>
        </div>
        {main?.edge ? <EdgeTag l={main} compact /> : null}
      </div>

      <div className="mt-2.5 grid grid-cols-2 gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.3fr)]">
        <Link href={href(main)} scroll={false} aria-current={activeKey === cardKey ? "true" : undefined}
          className={`col-span-2 grid grid-cols-2 gap-2 rounded-md ${activeKey === cardKey ? "ring-1 ring-model/60" : ""}`}>
          <MarketBox l={main} observed={main ? observedAt(main) : null} now={now} stale={main ? staleLine(main) : false} compact />
          <ModelBox mean={r.mean} median={r.median} range80={r.range80} supportLabel={c.label} supportCls={c.cls} compact />
        </Link>
        {main ? (
          <Link href={href(main)} scroll={false} className="col-span-2 flex flex-col justify-center gap-1.5 md:col-span-1">
            {r.atLine ? <OutcomeBar pr={r.atLine} l={main} compact /> : null}
            <PreferredChip p={r.preferred} line={r.atLine?.line ?? null} />
          </Link>
        ) : (
          <div className="col-span-2 flex flex-col justify-center gap-1 md:col-span-1">
            <span className="text-[0.68rem] text-faint">Model ladder · no market line, so no preferred outcome</span>
            <div className="flex flex-wrap gap-1.5">
              {r.ladder.map((l) => {
                const k = lineKey(r.id, l);
                return <LadderPill key={k} l={l} href={href(l)} active={k === activeKey} />;
              })}
            </div>
          </div>
        )}
      </div>

      {main && (quotedOthers.length || r.ladder.length) ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {quotedOthers.map((l) => {
            const k = lineKey(r.id, l);
            return <QuotedPill key={k} l={l} href={href(l)} active={k === activeKey} />;
          })}
          {r.ladder.length ? <span className="text-[0.65rem] text-faint">Model ladder</span> : null}
          {r.ladder.map((l) => {
            const k = lineKey(r.id, l);
            return <LadderPill key={k} l={l} href={href(l)} active={k === activeKey} />;
          })}
        </div>
      ) : null}
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
  const k = ladderSel?.threshold ?? (market ? market.threshold : null);
  const hit = (v: number | null) => (v == null || k == null ? null : (ladderSel ?? market)!.op === ">=" ? v >= k : v > k);
  const recent = r.recent.filter((g) => g.value != null);
  const closeHref = propsHref(league, { ...x.query }, { line: undefined });
  const title = `${r.name} ${x.category.label.toLowerCase()}`;
  const ms = d.marketStats;
  return (
    <div className={explicit ? "fixed inset-0 z-50 flex flex-col justify-end bg-black/60 lg:static lg:z-auto lg:block lg:bg-transparent" : "hidden lg:block"}>
    {explicit ? <Link href={closeHref} scroll={false} aria-label="Close details" className="min-h-[8vh] flex-1 lg:hidden" /> : null}
    <aside
      aria-label="Prop detail"
      className={`${explicit ? "max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-navy-600 bg-navy-950 p-3 pb-8 shadow-2xl lg:max-h-none lg:rounded-none lg:border-0 lg:bg-transparent lg:p-0 lg:pb-0 lg:shadow-none" : ""} lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto`}
    >
      {explicit ? <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-navy-600 lg:hidden" aria-hidden="true" /> : null}
      <TrackView item={{ href: propsHref(league, { game: r.gameId, cat: x.category.key }, { line: d.key }), label: title, sub: `${r.matchup} · ${league.toUpperCase()}` }} />
      <div className="space-y-3 rounded-lg border border-navy-700 bg-navy-900 p-4">
        <div className="flex items-start gap-2">
          <TeamBadge league={league} abbr={r.team} />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-faint">{x.category.label}</p>
            <h2 className="font-display text-xl font-700 leading-tight text-ink">{r.name}</h2>
            <p className="text-xs text-faint">{r.position} · {r.matchup}{x.game ? ` · ${formatKickoff(x.game.startTime)}` : ""}</p>
          </div>
          <FavoriteStar id={`${league}:${r.id}`} name={r.name} />
          {explicit ? <Link href={closeHref} scroll={false} className="rounded-md border border-navy-700 px-2 py-0.5 text-sm text-mute lg:hidden">Close</Link> : null}
        </div>

        <AvailabilityPanel r={r} />

        <MarketBox l={market} observed={market ? observedAt(market) : null} now={x.now} stale={market ? staleLine(market) : false} />
        {market ? (
          <>
            <MarketQuotes l={market} x={x} />
            {implied != null ? <p className="text-[0.68rem] text-faint">Market-implied chance of Yes (bid/ask midpoint): {formatPct(implied)}{market.market ? "" : " (wide or thin quote, for reference only)"}.</p> : null}
          </>
        ) : null}

        <ModelBox mean={r.mean} median={r.median} range80={r.range80} supportLabel={`${CONF[r.support].label}: ${r.supportNote}`} supportCls={CONF[r.support].cls} />
        {r.grid ? <DistributionChart grid={r.grid} line={markLine} label={x.category.label.toLowerCase()} /> : null}

        {pr && market ? <OutcomeBar pr={pr} l={market} /> : null}
        {ladderSel ? (
          <p className="rounded-md border border-navy-700 p-2.5 text-xs text-mute">
            Model threshold, not a market line: Model Room gives <span className="text-model">{formatPct(ladderSel.modelProb)}</span> to {lineLabel(ladderSel)} {x.category.label.toLowerCase()}.
          </p>
        ) : null}
        {market ? <PreferredBlock p={pref} pr={pr} mean={r.mean} /> : <p className="text-xs text-faint">No preferred outcome without a market line.</p>}

        {market?.edge ? (
          <section aria-label="Model-implied value" className="rounded-md border border-navy-700 p-2.5 text-xs">
            <div className="flex items-center justify-between"><span className="font-600 text-edge">Model-implied expected value (unverified)</span><EdgeTag l={market} /></div>
            <p className="mt-1 text-mute">
              {market.edge.side === "yes" ? "Yes" : "No"} at {cents(market.edge.price)}¢ on {providerName(market.edge.provider)}. Model chance − price − fee ={" "}
              <span className="text-edge">+{(market.edge.ev * 100).toFixed(1)}¢</span> per $1 contract.{market.edge.grade !== "strong" ? ` Data warnings: ${market.edge.reasons.join("; ")}.` : ""} This assumes the model&apos;s probability is right; it is not a verified edge.
            </p>
          </section>
        ) : null}

        <section aria-label="Why the model lands here" className="space-y-1.5">
          <h3 className="text-xs font-600 text-ink">Why the model lands here</h3>
          {isLocked(r.contributions) ? (
            <div className="flex items-center gap-2 text-xs text-faint"><span>The model&apos;s step-by-step record is part of Pro.</span><LockedCell requires={r.contributions.requires} /></div>
          ) : (
            <Contributions c={r.contributions} league={league} />
          )}
        </section>

        <InjuriesFreshness league={league} team={r.team} opp={r.opp} injuries={x.injuries} modelAbsences={r.modelAbsences}
          generatedAt={x.generatedAt} feedAt={x.injuryFeedAt} lineSeen={market ? observedAt(market) : null} version={x.model.version} />

        {recent.length ? (
          <section aria-label="Recent games">
            <h3 className="mb-1 text-xs font-600 text-faint">Last {recent.length} games</h3>
            <ul className="flex gap-1">
              {recent.map((g) => (
                <li key={g.date} className={`flex-1 rounded border px-1 py-1 text-center ${hit(g.value) ? "border-good/50" : "border-navy-700"}`} title={`${g.date} vs ${g.opp}`}>
                  <div className={`font-mono text-sm ${hit(g.value) ? "text-good" : "text-ink"}`}>{formatNumber(g.value!)}</div>
                  <div className="text-[0.6rem] text-faint">{g.opp}</div>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-[0.68rem] text-faint">{k != null ? `Green cleared ${lineLabel((ladderSel ?? market)!)}. ` : ""}Past games only; the model does not use this row.</p>
          </section>
        ) : null}

        <details className="text-xs">
          <summary className="cursor-pointer font-600 text-faint">Player and opponent inputs</summary>
          {isLocked(r.inputs) ? (
            <div className="mt-1 flex items-center gap-2 text-faint">
              <span>Model inputs (usage, matchup factors) are part of Pro.</span>
              <LockedCell requires={r.inputs.requires} />
            </div>
          ) : (
            <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
              {Object.entries(r.inputs).filter(([, v]) => v !== null && typeof v !== "object").map(([kk, v]) => (
                <div key={kk} className="flex justify-between gap-2"><dt className="text-faint">{kk.replaceAll("_", " ")}</dt><dd className="font-mono text-mute">{String(v)}</dd></div>
              ))}
            </dl>
          )}
        </details>

        {ms ? (
          <section aria-label="Historical performance" className="text-xs text-mute">
            <h3 className="mb-1 font-600 text-faint">How this category tested</h3>
            {ms.n.toLocaleString()} {x.category.label.toLowerCase()} thresholds in held-out seasons: log loss {ms.log_loss.toFixed(3)}
            {ms.baseline_log_loss != null ? ` vs ${ms.baseline_log_loss.toFixed(3)} for recent form` : ""}
            {ms.ece != null ? `, calibration error ${(ms.ece * 100).toFixed(1)}%` : ""}. <Link href={`/performance/props?sport=${league}&cat=${x.category.key}`} className="text-model hover:underline">Validation by category</Link>
          </section>
        ) : null}
        <p className="text-[0.65rem] text-faint">The model never sees market prices; market lines are shown beside it, not fed into it.</p>
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

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_23rem] xl:grid-cols-[13rem_minmax(0,1fr)_24rem]">
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
              <ul className="space-y-2">{rows.map((r) => <PlayerRow key={`${r.gameId}:${r.id}`} r={r} league={league} q={x.query} activeKey={activeKey} now={x.now} />)}</ul>
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
