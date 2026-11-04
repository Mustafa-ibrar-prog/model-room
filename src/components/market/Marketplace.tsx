import Link from "next/link";
import { Confirmed, sourceLabel } from "@/components/injuries/InjuryFlags";
import { formatKickoff, formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { providerName } from "@/lib/providers";
import { getExplorer, lineKey, marketMid, SORTS, type ContractDetail, type Explorer, type ExplorerGame, type ExplorerQuery, type ExplorerRow } from "@/server/data/explorer";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import type { PropLineView } from "@/types/props";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell, LockedPanel, Unavailable } from "@/components/ui/primitives";
import { AutoSubmit } from "@/components/props/AutoSubmit";
import { age, cents, EdgeTag, flagText, fmt, GapBar, lineLabel, PROVIDERS, quoteBy } from "./bits";
import { FavoritesScope, FavoriteStar, RecentlyViewed, TrackView } from "./local";

const CONF = { ok: { label: "High", cls: "text-model" }, limited: { label: "Medium", cls: "text-mute" }, insufficient: { label: "Low", cls: "text-faint" } } as const;

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
/** Who is quoting this line ("Polymarket", "Kalshi"), for the market label. */
function quotedBy(l: PropLineView): string | null {
  const q = l.quotes.find((v) => v.usable && v.mid != null) ?? l.quotes.find((v) => v.mid != null && !v.flags.includes("crossed book"));
  return q ? providerName(q.provider).replace(" US", "") : null;
}

/** The line that matters most for this player: the market's main line, or the model's coin-flip line. */
function MainLine({ l, href, active, stat }: { l: PropLineView; href: string; active: boolean; stat: string }) {
  const mid = marketMid(l);
  const by = quotedBy(l);
  const gap = mid != null ? Math.round((l.modelProb - mid) * 100) : null;
  return (
    <Link
      href={href}
      scroll={false}
      aria-current={active ? "true" : undefined}
      className={`block min-w-0 flex-1 rounded-md border px-3 py-2 transition-colors md:max-w-[19rem] ${active ? "border-model bg-model/10" : "border-navy-700 bg-navy-850 hover:border-navy-600"}`}
    >
      <section aria-label={mid != null ? "Market line" : "Main line"}>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm">
            <span className="font-mono font-700 text-ink">{lineLabel(l)}</span> <span className="text-mute">{stat}</span>
          </span>
          {l.edge ? <EdgeTag l={l} compact /> : gap != null && Math.abs(gap) >= 3 ? <span className="font-mono text-[0.7rem] text-mute">{gap > 0 ? "+" : ""}{gap} pts</span> : null}
        </div>
        <div className="mt-1 grid grid-cols-2 gap-3">
          <div>
            <div className="text-[0.65rem] text-faint">Model</div>
            <div className="font-display text-2xl font-700 leading-none text-model">{formatPct(l.modelProb)}</div>
          </div>
          <div>
            <div className="text-[0.65rem] text-faint">{by ? `${by}${l.market ? "" : " (wide)"}` : "Market"}</div>
            {mid != null ? (
              <div className="font-display text-2xl font-700 leading-none text-market">{formatPct(mid)}</div>
            ) : (
              <div className="pt-1.5 text-xs text-faint">No line listed</div>
            )}
          </div>
        </div>
        <GapBar model={l.modelProb} market={mid} edge={Boolean(l.edge)} className="mt-2" />
      </section>
    </Link>
  );
}

/** Every other line, as a small pill: line, model %, market % when there is one. */
function LinePill({ l, href, active }: { l: PropLineView; href: string; active: boolean }) {
  const mid = marketMid(l);
  return (
    <Link
      href={href}
      scroll={false}
      aria-current={active ? "true" : undefined}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${active ? "border-model bg-model/15" : "border-navy-700 bg-navy-900 hover:border-navy-600"}`}
    >
      <span className="font-mono text-mute">{lineLabel(l)}</span>
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

function PlayerRow({ r, league, q, activeKey, stat }: { r: ExplorerRow; league: League; q: ExplorerQuery; activeKey: string | null; stat: string }) {
  const c = CONF[r.support];
  const href = (l: PropLineView) => propsHref(league, { ...q, game: q.game ?? r.gameId }, { line: lineKey(r.id, l) });
  const main = r.headline;
  const others = r.lines.filter((l) => l !== main);
  return (
    <li data-fav-id={`${league}:${r.id}`} className="rounded-lg border border-navy-700 bg-navy-900 p-3">
      <div className="flex flex-col gap-2.5 md:flex-row md:items-center md:gap-4">
        <div className="flex min-w-0 items-center gap-2 md:w-72 md:shrink-0">
          <FavoriteStar id={`${league}:${r.id}`} name={r.name} />
          <TeamBadge league={league} abbr={r.team} size="sm" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-600 text-ink">{r.name}</div>
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
          <section aria-label="Model Room projection" className="shrink-0 text-right">
            <div className="text-[0.6rem] text-faint">Projection</div>
            <div className="font-display text-xl font-700 leading-none text-model">{fmt(r.median)}</div>
            <div className={`text-[0.62rem] ${c.cls}`}>{c.label} confidence</div>
          </section>
        </div>
        {main ? <MainLine l={main} href={href(main)} active={lineKey(r.id, main) === activeKey} stat={stat} /> : null}
        {others.length ? (
          <div className="-mx-3 flex gap-1.5 overflow-x-auto px-3 md:mx-0 md:flex-1 md:flex-wrap md:px-0">
            {others.map((l) => {
              const k = lineKey(r.id, l);
              return <LinePill key={k} l={l} href={href(l)} active={k === activeKey} />;
            })}
          </div>
        ) : null}
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ detail
function Detail({ d, league, x, explicit }: { d: ContractDetail; league: League; x: Extract<Explorer, { ok: true }>; explicit: boolean }) {
  const { row: r, line: l } = d;
  const qb = quoteBy(l);
  const implied = marketMid(l);
  const wide = implied != null && !l.market;
  const diff = implied != null ? Math.round((l.modelProb - implied) * 100) : null;
  const ms = d.marketStats;
  const k = l.threshold;
  const hit = (v: number | null) => (v == null ? null : l.op === ">=" ? v >= k : v > k);
  const recent = r.recent.filter((g) => g.value != null);
  const closeHref = propsHref(league, { ...x.query }, { line: undefined });
  const title = `${r.name} ${lineLabel(l)} ${x.category.label.toLowerCase()}`;
  return (
    <div className={explicit ? "fixed inset-0 z-50 flex flex-col justify-end bg-black/60 lg:static lg:z-auto lg:block lg:bg-transparent" : "hidden lg:block"}>
    {explicit ? <Link href={closeHref} scroll={false} aria-label="Close details" className="min-h-[8vh] flex-1 lg:hidden" /> : null}
    <aside
      aria-label="Contract detail"
      className={`${explicit ? "max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-navy-600 bg-navy-950 p-3 pb-8 shadow-2xl lg:max-h-none lg:rounded-none lg:border-0 lg:bg-transparent lg:p-0 lg:pb-0 lg:shadow-none" : ""} lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto`}
    >
      {explicit ? <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-navy-600 lg:hidden" aria-hidden="true" /> : null}
      <TrackView item={{ href: propsHref(league, { game: r.gameId, cat: x.category.key }, { line: d.key }), label: title, sub: `${r.matchup} · ${league.toUpperCase()}` }} />
      <div className="space-y-3 rounded-lg border border-navy-700 bg-navy-900 p-4">
        <div className="flex items-start gap-2">
          <TeamBadge league={league} abbr={r.team} />
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-xl font-700 leading-tight text-ink">{r.name}</h2>
            <p className="text-xs text-faint">{r.position} · {r.matchup}{x.game ? ` · ${formatKickoff(x.game.startTime)}` : ""}</p>
          </div>
          <FavoriteStar id={`${league}:${r.id}`} name={r.name} />
          {explicit ? <Link href={closeHref} scroll={false} className="rounded-md border border-navy-700 px-2 py-0.5 text-sm text-mute lg:hidden">Close</Link> : null}
        </div>

        <AvailabilityPanel r={r} />

        <div className="flex flex-wrap gap-1">
          {r.lines.map((o) => {
            const key = lineKey(r.id, o);
            return (
              <Link key={key} href={propsHref(league, { ...x.query, game: x.query.game ?? r.gameId }, { line: key })} scroll={false}
                className={`rounded border px-1.5 py-0.5 font-mono text-xs ${key === d.key ? "border-model bg-model/10 text-ink" : "border-navy-700 text-mute hover:text-ink"}`}>
                {lineLabel(o)}
              </Link>
            );
          })}
        </div>
        <p className="text-sm text-ink">{lineLabel(l)} {x.category.label.toLowerCase()}</p>

        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-md bg-model/10 p-2">
            <div className="text-[0.65rem] font-600 uppercase tracking-wider text-model">Model</div>
            <div className="font-display text-2xl font-700 text-model">{formatPct(l.modelProb)}</div>
          </div>
          <div className={`rounded-md p-2 ${implied != null ? "bg-market/10" : "bg-navy-850"}`}>
            <div className={`text-[0.65rem] font-600 uppercase tracking-wider ${implied != null ? "text-market" : "text-faint"}`}>Market{wide ? " (wide)" : ""}</div>
            <div className={`font-display text-2xl font-700 ${implied != null ? "text-market" : "text-faint"}`}>{implied != null ? formatPct(implied) : "–"}</div>
          </div>
          <div className="rounded-md bg-navy-850 p-2">
            <div className="text-[0.65rem] font-600 uppercase tracking-wider text-faint">Gap</div>
            <div className="font-display text-2xl font-700 text-ink">{diff == null ? "–" : `${diff > 0 ? "+" : ""}${diff}`}</div>
          </div>
        </div>
        <GapBar model={l.modelProb} market={implied} edge={Boolean(l.edge)} />

        <section aria-label="Market quotes">
          <h3 className="mb-1 text-xs font-600 uppercase tracking-wider text-market">Actual market</h3>
          <table className="w-full text-xs">
            <thead className="text-faint"><tr><th className="py-1 text-left font-500">Exchange</th><th className="text-right font-500">Bid/Ask</th><th className="text-right font-500">Implied</th><th className="text-right font-500">Size</th><th className="text-right font-500">Quote</th></tr></thead>
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
                      <td colSpan={4} className="text-right text-faint">Market unavailable</td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        <section aria-label="Edge" className="rounded-md border border-navy-700 p-2.5 text-xs">
          {l.edge ? (
            <>
              <div className="flex items-center justify-between"><span className="font-600 text-edge">Estimated edge</span><EdgeTag l={l} /></div>
              <p className="mt-1 text-mute">
                Buy {l.edge.side === "yes" ? "Yes" : "No"} at {cents(l.edge.price)}¢ on {providerName(l.edge.provider)}. Expected value = model chance − price − fee ={" "}
                <span className="text-edge">+{(l.edge.ev * 100).toFixed(1)}¢</span> per $1 contract.{l.edge.grade !== "strong" ? ` Lean only: ${l.edge.reasons.join("; ")}.` : ""}
              </p>
            </>
          ) : (
            <p className="text-faint">{l.market ? "No edge at the current executable price after fees." : "No usable exchange price, so no edge is calculated."}</p>
          )}
        </section>

        <section aria-label="Model Room projection" className="space-y-1.5">
          <h3 className="text-xs font-600 uppercase tracking-wider text-model">Model Room projection</h3>
          <dl className="grid grid-cols-4 gap-2 text-center">
            {[["Mean", r.mean], ["Median", r.median], ["SD", r.sd]].map(([lab, v]) => (
              <div key={lab as string}><dt className="text-[0.65rem] text-faint">{lab}</dt><dd className="font-mono text-sm text-ink">{fmt(v as number)}</dd></div>
            ))}
            <div><dt className="text-[0.65rem] text-faint">80% range</dt><dd className="font-mono text-sm text-ink">{fmt(r.range80[0])}–{fmt(r.range80[1])}</dd></div>
          </dl>
          <p className="text-xs text-mute"><span className={CONF[r.support].cls}>{CONF[r.support].label} confidence</span>: {r.supportNote}</p>
        </section>

        {recent.length ? (
          <section aria-label="Recent games">
            <h3 className="mb-1 text-xs font-600 uppercase tracking-wider text-faint">Last {recent.length} games</h3>
            <ul className="flex gap-1">
              {recent.map((g) => (
                <li key={g.date} className={`flex-1 rounded border px-1 py-1 text-center ${hit(g.value) ? "border-good/50" : "border-navy-700"}`} title={`${g.date} vs ${g.opp}`}>
                  <div className={`font-mono text-sm ${hit(g.value) ? "text-good" : "text-ink"}`}>{formatNumber(g.value!)}</div>
                  <div className="text-[0.6rem] text-faint">{g.opp}</div>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-[0.68rem] text-faint">Green cleared {lineLabel(l)}. Past games only.</p>
          </section>
        ) : null}

        <section aria-label="Model inputs" className="text-xs">
          <h3 className="mb-1 font-600 uppercase tracking-wider text-faint">Player and opponent inputs</h3>
          {isLocked(r.inputs) ? (
            <div className="flex items-center gap-2 text-faint">
              <span>Model inputs (usage, matchup factors) are part of Pro.</span>
              <LockedCell requires={r.inputs.requires} />
            </div>
          ) : (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
              {Object.entries(r.inputs).filter(([, v]) => v !== null && typeof v !== "object").map(([kk, v]) => (
                <div key={kk} className="flex justify-between gap-2"><dt className="text-faint">{kk.replaceAll("_", " ")}</dt><dd className="font-mono text-mute">{String(v)}</dd></div>
              ))}
            </dl>
          )}
        </section>

        {ms ? (
          <section aria-label="Historical performance" className="text-xs text-mute">
            <h3 className="mb-1 font-600 uppercase tracking-wider text-faint">How this market tested</h3>
            {ms.n.toLocaleString()} {x.category.label.toLowerCase()} lines in held-out seasons: log loss {ms.log_loss.toFixed(3)}
            {ms.baseline_log_loss != null ? ` vs ${ms.baseline_log_loss.toFixed(3)} for recent form` : ""}
            {ms.ece != null ? `, calibration error ${(ms.ece * 100).toFixed(1)}%` : ""}. <Link href={`/performance?sport=${league}`} className="text-model hover:underline">Details</Link>
          </section>
        ) : null}
        <p className="text-[0.65rem] text-faint">Model run {formatTimestamp(x.generatedAt)}. The model never sees exchange prices.</p>
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
  const detail: ContractDetail | null = !isLocked(x.detail) && x.detail ? x.detail
    : !isLocked(rows) && rows.length && rows[0].headline ? { row: rows[0], line: rows[0].headline, key: lineKey(rows[0].id, rows[0].headline), marketStats: x.backtest?.by_market?.[x.category.key] ?? null }
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
            Only your test-site login sees these; nothing is stored, and production never shows them. Contract sizes aren&apos;t in the listing, so edges are leans at most.
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
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-model" />Model</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-market" />Market</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-edge" />Edge after fees</span>
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
              <option value="edges">With an edge</option>
              <option value="strong">Strong edges only</option>
              <option value="ok">High confidence</option>
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
              <ul className="space-y-2">{rows.map((r) => <PlayerRow key={`${r.gameId}:${r.id}`} r={r} league={league} q={x.query} activeKey={activeKey} stat={statLabel} />)}</ul>
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
        Market-implied probability is the midpoint of an exchange&apos;s bid and ask. Edges use the price you would actually pay (the ask) after the exchange fee,
        from quotes under {x.rules.max_age_min} minutes old with a spread under {(x.rules.max_spread * 100).toFixed(0)}¢. Struck-through prices are stale,
        thin or one-sided and are never used.
      </p>
    </div>
  );
}
