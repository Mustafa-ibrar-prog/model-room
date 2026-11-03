import Link from "next/link";
import { formatKickoff, formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { providerName } from "@/lib/providers";
import { getExplorer, lineKey, SORTS, type ContractDetail, type Explorer, type ExplorerGame, type ExplorerQuery, type ExplorerRow } from "@/server/data/explorer";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import type { PropLineView } from "@/types/props";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell, LockedPanel, Unavailable } from "@/components/ui/primitives";
import { AutoSubmit } from "@/components/props/AutoSubmit";
import { age, cents, EdgeTag, flagText, fmt, GapBar, lineLabel, PROVIDERS, quoteBy } from "./bits";
import { FavoritesScope, FavoriteStar, RecentlyViewed, TrackView } from "./local";

const CONF = { ok: { label: "High", cls: "text-model" }, limited: { label: "Medium", cls: "text-mute" }, insufficient: { label: "Low", cls: "text-faint" } } as const;
const SHORT: Record<string, string> = { polymarket_us: "PM", kalshi: "K" };

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
    <nav aria-label="Games" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 lg:hidden">
      {x.games.map((g) => {
        const on = g.id === x.game?.id && !x.searchAll;
        return (
          <Link
            key={g.id}
            href={propsHref(league, { cat: x.query.cat, sort: x.query.sort, only: x.query.only }, { game: g.id })}
            scroll={false}
            aria-current={on ? "page" : undefined}
            className={`shrink-0 rounded-lg border px-2.5 py-1.5 ${on ? "border-model bg-model/10" : "border-navy-700 bg-navy-900"}`}
          >
            <span className="flex items-center gap-1">
              <TeamBadge league={league} abbr={g.away.abbr} size="sm" />
              <span className="text-[0.7rem] text-faint">@</span>
              <TeamBadge league={league} abbr={g.home.abbr} size="sm" />
            </span>
            <span className="mt-0.5 block text-center font-mono text-[0.65rem] text-faint">{dayLabel(g.gameDate).split(", ")[0]} {time(g)}</span>
          </Link>
        );
      })}
    </nav>
  );
}

// ------------------------------------------------------------------ contracts
function Contract({ l, href, active }: { l: PropLineView; href: string; active: boolean }) {
  const qb = quoteBy(l);
  const implied = l.market?.mid ?? null;
  return (
    <Link
      href={href}
      scroll={false}
      aria-current={active ? "true" : undefined}
      className={`block w-[7.75rem] shrink-0 rounded-md border px-2 py-1.5 transition-colors ${active ? "border-model bg-model/10" : "border-navy-700 bg-navy-900 hover:border-navy-600"}`}
    >
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[0.72rem] text-ink">{lineLabel(l)}</span>
        <span className="font-display text-base font-700 leading-none text-model">{formatPct(l.modelProb)}</span>
      </div>
      <GapBar model={l.modelProb} market={implied} edge={Boolean(l.edge)} className="my-1.5" />
      <div className="flex items-center justify-between gap-1 font-mono text-[0.64rem]">
        {Object.keys(qb).length ? (
          <span className="flex gap-1.5">
            {PROVIDERS.filter((p) => qb[p]).map((p) => (
              <span key={p} className={qb[p]!.usable ? "text-market" : "text-faint line-through"} title={`${providerName(p)} ${qb[p]!.usable ? "" : `(${flagText(qb[p]!.flags)})`}`}>
                {SHORT[p]} {qb[p]!.mid != null ? `${cents(qb[p]!.mid)}¢` : "–"}
              </span>
            ))}
          </span>
        ) : (
          <span className="text-faint">No market</span>
        )}
        <EdgeTag l={l} compact />
      </div>
    </Link>
  );
}

/** The market's main line next to ours: "Market 25+ at 48% · Model 61%". */
function MarketLine({ r }: { r: ExplorerRow }) {
  const h = r.headline;
  if (!h?.market || h.market.mid == null) return null;
  const gap = Math.round((h.modelProb - h.market.mid) * 100);
  return (
    <section aria-label="Market line" className="flex shrink-0 items-center gap-3 rounded-md bg-navy-850 px-2.5 py-1.5 font-mono text-[0.72rem] md:w-44 md:flex-col md:items-start md:gap-0.5">
      <span className="text-market">Market {lineLabel(h)} · {formatPct(h.market.mid)}</span>
      <span className="text-model">Model {formatPct(h.modelProb)}</span>
      {Math.abs(gap) >= 3 ? <span className={Math.abs(gap) >= 8 ? "text-edge" : "text-mute"}>{gap > 0 ? "+" : ""}{gap} pts</span> : null}
    </section>
  );
}

function PlayerRow({ r, league, q, activeKey }: { r: ExplorerRow; league: League; q: ExplorerQuery; activeKey: string | null }) {
  const c = CONF[r.support];
  return (
    <li data-fav-id={`${league}:${r.id}`} className="rounded-lg border border-navy-700 bg-navy-900 px-3 py-2.5">
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <div className="flex min-w-0 items-center gap-2 md:w-56 md:shrink-0">
          <FavoriteStar id={`${league}:${r.id}`} name={r.name} />
          <TeamBadge league={league} abbr={r.team} size="sm" />
          <div className="min-w-0">
            <div className="truncate font-600 text-ink">{r.name}</div>
            <div className="flex flex-wrap gap-x-2 text-[0.72rem] text-faint">
              <span>{r.position} · {r.matchup}</span>
              {r.injuryStatus ? <span className="text-edge">{r.injuryStatus}</span> : null}
            </div>
          </div>
          <section aria-label="Model Room projection" className="ml-auto text-right md:hidden">
            <div className="font-display text-xl font-700 leading-none text-model">{fmt(r.median)}</div>
            <div className={`text-[0.65rem] ${c.cls}`}>{c.label} confidence</div>
          </section>
        </div>
        <section aria-label="Model Room projection" className="hidden w-24 shrink-0 md:block">
          <div className="font-display text-xl font-700 leading-none text-model">{fmt(r.median)}</div>
          <div className="text-[0.65rem] text-faint">median · <span className={c.cls}>{c.label}</span></div>
        </section>
        <MarketLine r={r} />
        <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5">
          {r.lines.map((l) => {
            const k = lineKey(r.id, l);
            return <Contract key={k} l={l} href={propsHref(league, { ...q, game: q.game ?? r.gameId }, { line: k })} active={k === activeKey} />;
          })}
        </div>
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ detail
function Detail({ d, league, x, explicit }: { d: ContractDetail; league: League; x: Extract<Explorer, { ok: true }>; explicit: boolean }) {
  const { row: r, line: l } = d;
  const qb = quoteBy(l);
  const implied = l.market?.mid ?? null;
  const diff = implied != null ? Math.round((l.modelProb - implied) * 100) : null;
  const ms = d.marketStats;
  const k = l.threshold;
  const hit = (v: number | null) => (v == null ? null : l.op === ">=" ? v >= k : v > k);
  const recent = r.recent.filter((g) => g.value != null);
  const closeHref = propsHref(league, { ...x.query }, { line: undefined });
  const title = `${r.name} ${lineLabel(l)} ${x.category.label.toLowerCase()}`;
  return (
    <aside
      aria-label="Contract detail"
      className={`${explicit ? "fixed inset-0 z-50 overflow-y-auto bg-navy-950 p-4 lg:static lg:z-auto lg:bg-transparent lg:p-0" : "hidden lg:block"} lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto`}
    >
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
            <div className={`text-[0.65rem] font-600 uppercase tracking-wider ${implied != null ? "text-market" : "text-faint"}`}>Market</div>
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
  const providers = x.providers.filter((p) => p.provider !== "manual" || p.quotes > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-mute">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-model" />Model<span className="hidden sm:inline"> Room</span></span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-market" />Market<span className="hidden sm:inline"> (PM = Polymarket US, K = Kalshi)</span></span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-edge" />Edge<span className="hidden sm:inline"> after fees</span></span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-navy-600" />N/A</span>
        <span className="ml-auto hidden text-faint sm:inline">
          {providers.length ? providers.map((p) => `${providerName(p.provider)} ${p.quotes} prices`).join(" · ") : "No exchange prices connected"}
        </span>
      </div>

      {x.live ? (
        <p className="rounded-md border border-market/40 bg-market/10 px-3 py-2 text-xs text-mute">
          <span className="font-600 text-market">Owner view · live Polymarket US prices.</span>{" "}
          Fetched {formatTimestamp(x.live.fetchedAt)} for {x.live.games === 1 ? "this game" : `${x.live.games} games`} ({x.live.found} found on Polymarket, {x.live.matched} lines matched).
          Only your test-site login sees these; nothing is stored, and production never shows them. Contract sizes aren&apos;t in the listing, so edges are leans at most.
        </p>
      ) : null}

      <GameChips league={league} x={x} />

      <div className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_22rem]">
        <div className="hidden space-y-5 lg:block">
          <GameRail league={league} x={x} />
          <div>
            <h3 className="px-2 pb-1 text-xs text-faint">Recently viewed</h3>
            <RecentlyViewed />
          </div>
        </div>

        <div className="min-w-0 space-y-3">
          {x.searchAll ? (
            <h2 className="font-display text-xl font-600 text-ink">Search: “{query.q}” across every {league.toUpperCase()} game</h2>
          ) : game ? (
            <div className="flex flex-wrap items-center gap-2">
              <TeamBadge league={league} abbr={game.away.abbr} />
              <span className="font-display text-xl font-600 text-ink">{game.away.name} <span className="text-faint">at</span> {game.home.name}</span>
              <TeamBadge league={league} abbr={game.home.abbr} />
              <span className="ml-auto text-sm text-mute">{formatKickoff(game.startTime)}</span>
            </div>
          ) : null}

          <nav aria-label="Prop categories" className="-mx-1 flex gap-1 overflow-x-auto px-1">
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

          <form action="/props" className="flex flex-wrap items-end gap-2">
            <input type="hidden" name="sport" value={league} />
            {query.game ? <input type="hidden" name="game" value={query.game} /> : null}
            {query.date ? <input type="hidden" name="date" value={query.date} /> : null}
            <input type="hidden" name="cat" value={x.category.key} />
            <label className="sr-only" htmlFor="q">Search players or teams</label>
            <input id="q" name="q" defaultValue={x.query.q ?? ""} placeholder="Search players or teams" className={`${sel} w-full sm:w-56`} />
            {game && !x.searchAll ? (
              <select name="team" aria-label="Team" defaultValue={x.query.team ?? ""} className={sel}>
                <option value="">Both teams</option>
                <option value={game.away.abbr}>{game.away.abbr}</option>
                <option value={game.home.abbr}>{game.home.abbr}</option>
              </select>
            ) : null}
            <select name="only" aria-label="Show" defaultValue={x.query.only ?? ""} className={sel}>
              <option value="">All players</option>
              <option value="priced">With exchange prices</option>
              <option value="edges">With an edge</option>
              <option value="strong">Strong edges only</option>
              <option value="ok">High confidence</option>
            </select>
            <select name="sort" aria-label="Sort" defaultValue={x.sort} className={sel}>
              {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <button type="submit" className="rounded-full bg-model px-4 py-1.5 text-sm font-600 text-navy-950">Go</button>
            {x.query.q ? <Link href={propsHref(league, { cat: x.query.cat, game: query.game }, {})} className="text-sm text-mute hover:text-ink">Clear search</Link> : null}
            <AutoSubmit />
          </form>

          {isLocked(rows) ? (
            <LockedPanel requires={rows.requires} title="Player props are part of Plus" body={`Every player's projection, probabilities and exchange comparison for ${x.games.length} upcoming games.`} />
          ) : rows.length === 0 ? (
            <p className="px-1 py-6 text-center text-sm text-mute">
              {x.totalPlayers ? "No players match. Try another search or filter." : `No ${x.category.label.toLowerCase()} projections for this game.`}
            </p>
          ) : (
            <FavoritesScope>
              <ul className="space-y-1.5">{rows.map((r) => <PlayerRow key={`${r.gameId}:${r.id}`} r={r} league={league} q={x.query} activeKey={activeKey} />)}</ul>
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
