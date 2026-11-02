import Link from "next/link";
import { formatKickoff, formatPct, formatTimestamp } from "@/lib/format";
import { getExplorer, SORTS, type ExplorerGame, type ExplorerQuery, type ExplorerRow } from "@/server/data/explorer";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import type { PropLineView } from "@/types/props";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedPanel, Panel, SourceStamp, Unavailable } from "@/components/ui/primitives";
import { AutoSubmit } from "./AutoSubmit";

const PROVIDER: Record<string, string> = { polymarket_us: "Polymarket US", kalshi: "Kalshi" };
const VARIANT: Record<string, string> = { espn_ppr: "ESPN", sleeper_ppr: "Sleeper" };

const providerName = (p: string) => (p.startsWith("manual:") ? p.slice(7) : (PROVIDER[p] ?? p));
const fmt = (n: number) => (Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(1));

function lineLabel(l: PropLineView): string {
  const n = Number.isInteger(l.threshold) ? l.threshold.toFixed(0) : l.threshold.toFixed(1);
  return `${l.op === ">=" ? `${n}+` : `Over ${n}`}${l.variant ? ` ${VARIANT[l.variant] ?? l.variant}` : ""}`;
}

function href(league: League, q: ExplorerQuery, patch: Partial<ExplorerQuery>): string {
  const all = { ...q, ...patch };
  const p = new URLSearchParams({ sport: league });
  for (const [k, v] of Object.entries(all)) if (v) p.set(k, String(v));
  return `/props?${p.toString()}`;
}

function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

function GamePicker({ league, games, selected, q }: { league: League; games: ExplorerGame[]; selected: string | null; q: ExplorerQuery }) {
  return (
    <nav aria-label="Games" className="-mx-1 flex items-stretch gap-2 overflow-x-auto px-1 pb-1">
      {games.map((g, i) => {
        const on = g.id === selected;
        const newDay = i === 0 || g.gameDate !== games[i - 1].gameDate;
        return (
          <div key={g.id} className="flex shrink-0 items-stretch gap-2">
            {newDay ? (
              <span className="flex w-10 shrink-0 items-center justify-center text-center font-mono text-[0.65rem] uppercase leading-tight tracking-wider text-faint">
                {dayLabel(g.gameDate).replace(",", "")}
              </span>
            ) : null}
            <Link
              href={href(league, { cat: q.cat, sort: q.sort, only: q.only }, { game: g.id })}
              scroll={false}
              aria-current={on ? "page" : undefined}
              aria-label={`${g.away.name} at ${g.home.name}`}
              className={`rounded-lg border px-3 py-2 ${on ? "border-model bg-model/10" : "border-navy-700 bg-navy-900 hover:border-navy-600"}`}
            >
              <span className="flex items-center gap-1.5">
                <TeamBadge league={league} abbr={g.away.abbr} size="sm" />
                <span className="text-xs text-faint">at</span>
                <TeamBadge league={league} abbr={g.home.abbr} size="sm" />
              </span>
              <span className="mt-1 block text-[0.72rem] text-mute">
                {g.status === "started" ? "Started" : formatKickoff(g.startTime).split(", ").slice(-1)[0]}
              </span>
            </Link>
          </div>
        );
      })}
    </nav>
  );
}

const CONFIDENCE = {
  ok: { label: "High", cls: "border-model/50 text-model" },
  limited: { label: "Medium", cls: "border-navy-600 text-mute" },
  insufficient: { label: "Low", cls: "border-navy-600 text-faint" },
} as const;

const FLAG: Record<string, string> = { stale: "Stale", thin: "Thin", "thin at ask": "Thin", "one-sided": "One-sided", different: "Different contract" };
const flagText = (flags: string[]) => [...new Set(flags.map((f) => FLAG[f] ?? f))].join(", ");
const cents = (x: number | null) => (x == null ? "–" : `${Math.round(x * 100)}`);

function age(iso: string, now: number): string {
  const m = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

function size(n: number | null): string | null {
  if (n == null) return null;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${Math.round(n)}`;
}

/** One threshold: the model on top (teal), the market underneath (blue, one line per exchange), then the gap and any edge (orange). */
function LineCell({ l, highlight, now }: { l: PropLineView; highlight: boolean; now: number }) {
  const implied = l.market?.mid ?? null;
  const diff = implied != null ? Math.round((l.modelProb - implied) * 100) : null;
  return (
    <div className={`w-[9.75rem] shrink-0 overflow-hidden rounded-md border ${highlight ? "border-navy-600" : "border-navy-700"}`}>
      <div className="flex items-baseline justify-between bg-navy-850 px-2 py-1 font-mono text-[0.72rem] text-ink">
        <span>{lineLabel(l)}</span>
        {highlight ? <span className="h-1.5 w-1.5 rounded-full bg-ink/50" title="Line closest to even for the model" /> : null}
      </div>
      <div className="flex items-baseline justify-between border-l-[3px] border-model bg-model/10 px-2 py-1">
        <span className="text-[0.62rem] font-600 uppercase tracking-wider text-model">Model</span>
        <span className="font-display text-lg font-700 leading-tight text-model">{formatPct(l.modelProb)}</span>
      </div>
      {l.quotes.length ? (
        <div className="border-l-[3px] border-market bg-market/10 px-2 py-1">
          <div className="flex items-baseline justify-between">
            <span className="text-[0.62rem] font-600 uppercase tracking-wider text-market">Market</span>
            {implied != null ? (
              <span className="font-display text-lg font-700 leading-tight text-market" title="Market-implied probability: midpoint of the best usable bid and ask">{formatPct(implied)}</span>
            ) : (
              <span className="text-[0.68rem] text-faint">no usable price</span>
            )}
          </div>
          <ul className="mt-0.5 space-y-0.5">
            {l.quotes.map((q, i) => {
              const liq = size(q.askSize);
              return (
                <li key={`${q.provider}${i}`} className={`font-mono text-[0.64rem] leading-snug ${q.usable ? "text-market" : "text-faint"}`}>
                  <span className="flex justify-between gap-1">
                    <span className={q.usable ? "" : "line-through decoration-1"}>{providerName(q.provider)}</span>
                    <span title="Bid / ask in cents">{cents(q.bid)}/{cents(q.ask)}¢</span>
                  </span>
                  <span className="flex justify-between gap-1 text-[0.6rem] opacity-80">
                    <span>{age(q.capturedAt, now)}</span>
                    {q.usable ? <span>{liq ? `${liq} at ask` : "size n/a"}</span> : <span className="font-600 text-ink/70">{flagText(q.flags)}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <div className="flex items-baseline justify-between border-l-[3px] border-navy-600 bg-navy-850/60 px-2 py-1">
          <span className="text-[0.62rem] font-600 uppercase tracking-wider text-faint">Market</span>
          <span className="text-[0.68rem] text-faint">unavailable</span>
        </div>
      )}
      <div className="flex min-h-[1.9rem] items-center justify-between gap-1 border-t border-navy-700/70 px-2 py-1">
        <span className={`font-mono text-[0.7rem] ${diff == null ? "text-faint" : "text-ink"}`} title="Model probability minus market-implied probability, in percentage points">
          {diff == null ? "No comparison" : `${diff > 0 ? "+" : ""}${diff} pts`}
        </span>
        {l.edge ? (
          <span
            title={`${l.edge.grade === "strong" ? "Strong edge" : `Lean, not strong: ${l.edge.reasons.join("; ")}`}. Buy ${l.edge.side === "yes" ? "Yes" : "No"} at ${cents(l.edge.price)}¢ on ${providerName(l.edge.provider)}${l.edge.fee != null ? `, fee ${(l.edge.fee * 100).toFixed(1)}¢` : ""}; expected value after the fee.`}
            className={`whitespace-nowrap rounded px-1 py-px font-mono text-[0.66rem] ${l.edge.grade === "strong" ? "bg-edge font-600 text-navy-950" : "border border-edge/70 text-edge"}`}
          >
            {l.edge.grade === "strong" ? "Edge" : "Lean"} {l.edge.side === "yes" ? "Y" : "N"} +{(l.edge.ev * 100).toFixed(1)}¢
          </span>
        ) : l.market ? (
          <span className="whitespace-nowrap font-mono text-[0.64rem] text-faint">no edge</span>
        ) : null}
      </div>
      {l.edge ? (
        <div className="bg-edge/10 px-2 py-0.5 font-mono text-[0.6rem] text-edge">
          Buy {l.edge.side === "yes" ? "Yes" : "No"} {cents(l.edge.price)}¢, {providerName(l.edge.provider)}, net of fee
        </div>
      ) : null}
    </div>
  );
}

function MarketSummary({ r, now }: { r: ExplorerRow; now: number }) {
  const quotes = r.lines.flatMap((l) => l.quotes);
  if (!quotes.length) {
    return (
      <div className="flex flex-wrap items-center gap-x-2 border-l-[3px] border-navy-600 bg-navy-850/60 px-3 py-1.5 text-xs">
        <span className="font-600 uppercase tracking-wider text-faint">Actual market</span>
        <span className="text-faint">Market unavailable: no Polymarket or Kalshi quote for these lines.</span>
      </div>
    );
  }
  const byProvider = new Map<string, typeof quotes>();
  for (const q of quotes) byProvider.set(q.provider, [...(byProvider.get(q.provider) ?? []), q]);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-l-[3px] border-market bg-market/10 px-3 py-1.5 text-xs">
      <span className="font-600 uppercase tracking-wider text-market">Actual market</span>
      {[...byProvider.entries()].map(([p, qs]) => {
        const usable = qs.filter((q) => q.usable).length;
        const latest = qs.map((q) => q.capturedAt).sort().at(-1)!;
        return (
          <span key={p} className={usable ? "text-market" : "text-faint"}>
            {providerName(p)}: {usable}/{qs.length} usable, {age(latest, now)}
            {usable < qs.length ? <span className="text-ink/70"> ({flagText(qs.filter((q) => !q.usable).flatMap((q) => q.flags))})</span> : null}
          </span>
        );
      })}
    </div>
  );
}

function PlayerRow({ r, league, now }: { r: ExplorerRow; league: League; now: number }) {
  const conf = CONFIDENCE[r.support];
  return (
    <li className="overflow-hidden rounded-lg border border-navy-700 bg-navy-900">
      <div className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(11rem,0.9fr)_minmax(12rem,1fr)_2.6fr] md:items-start">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <TeamBadge league={league} abbr={r.team} size="sm" />
            <span className="truncate font-display text-lg font-600 text-ink">{r.name}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-mute">
            <span>{r.position} vs {r.opp}</span>
            {r.injuryStatus ? <span className="text-ink">{r.injuryStatus}</span> : null}
          </div>
        </div>
        <section aria-label="Model Room projection" className="rounded-md border-l-[3px] border-model bg-model/10 px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-[0.62rem] font-600 uppercase tracking-wider text-model">Model Room projection</h4>
            <span title={r.supportNote} className={`whitespace-nowrap rounded border px-1.5 py-px text-[0.62rem] ${conf.cls}`}>{conf.label} confidence</span>
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-display text-3xl font-700 leading-none text-model">{fmt(r.median)}</span>
            <span className="text-xs text-model/80">median</span>
          </div>
          <dl className="mt-1 flex flex-wrap gap-x-3 font-mono text-[0.7rem] text-mute">
            <div><dt className="inline text-faint">mean </dt><dd className="inline">{fmt(r.mean)}</dd></div>
            <div><dt className="inline text-faint">sd </dt><dd className="inline">{fmt(r.sd)}</dd></div>
            <div><dt className="inline text-faint">80% </dt><dd className="inline">{fmt(r.range80[0])}–{fmt(r.range80[1])}</dd></div>
          </dl>
        </section>
        <div className="-mx-1 flex items-start gap-2 overflow-x-auto px-1 pb-1">
          {r.lines.map((l) => <LineCell key={`${l.op}${l.threshold}${l.variant}`} l={l} highlight={l === r.headline} now={now} />)}
        </div>
      </div>
      <MarketSummary r={r} now={now} />
      <details className="border-t border-navy-700/70 px-4 py-2">
        <summary className="cursor-pointer text-xs text-faint hover:text-mute">History and model inputs</summary>
        <div className="grid gap-4 py-2 text-xs md:grid-cols-2">
          <div>
            <h4 className="mb-1 font-mono uppercase tracking-wider text-faint">History behind the estimate</h4>
            <p className="text-mute">{r.supportNote}</p>
          </div>
          <div>
            {!isLocked(r.inputs) ? (
              <>
                <h4 className="mb-1 font-mono uppercase tracking-wider text-faint">Model inputs</h4>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                  {Object.entries(r.inputs)
                    .filter(([, v]) => v !== null && typeof v !== "object")
                    .map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-2">
                        <dt className="text-faint">{k.replaceAll("_", " ")}</dt>
                        <dd className="font-mono text-mute">{String(v)}</dd>
                      </div>
                    ))}
                </dl>
              </>
            ) : (
              <p className="text-faint">Model inputs (usage, matchup factors) are part of Pro.</p>
            )}
          </div>
        </div>
      </details>
    </li>
  );
}

function Legend() {
  const item = (cls: string, text: string) => (
    <span className="flex items-center gap-1.5"><span aria-hidden="true" className={`inline-block h-3 w-3 rounded-sm ${cls}`} />{text}</span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-mute">
      {item("bg-model", "Model Room projection")}
      {item("bg-market", "Actual market (Polymarket, Kalshi)")}
      {item("bg-edge", "Potential edge, after fees")}
      {item("bg-navy-600", "Unavailable or unusable")}
    </div>
  );
}

export async function PropsExplorer({ league, query }: { league: League; query: ExplorerQuery }) {
  const viewer = await getViewer();
  const x = await getExplorer(league, viewer.tier, query);
  if (!x.ok) return <Unavailable title={`${league.toUpperCase()} player props unavailable`} body={x.reason} />;
  const bt = x.backtest;
  const providers = x.providers.filter((p) => p.provider !== "manual" || p.quotes > 0);
  const game = x.game;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <SourceStamp>Model {x.model.version}, {x.model.status.split(":")[0]}</SourceStamp>
        <SourceStamp>Run {formatTimestamp(x.generatedAt)}</SourceStamp>
        {providers.length
          ? providers.map((p) => <SourceStamp key={p.provider}>{providerName(p.provider)}: {p.quotes} prices</SourceStamp>)
          : <SourceStamp>No exchange prices connected</SourceStamp>}
        {bt?.overall_vs_baseline ? (
          <SourceStamp>
            Tested {bt.test_seasons[0]}–{bt.test_seasons[bt.test_seasons.length - 1]}: log loss {bt.overall_vs_baseline.model.log_loss.toFixed(3)} vs{" "}
            {bt.overall_vs_baseline.baseline.log_loss.toFixed(3)} baseline
          </SourceStamp>
        ) : null}
      </div>

      <Legend />

      <GamePicker league={league} games={x.games} selected={game?.id ?? null} q={x.query} />

      {game ? (
        <Panel className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-navy-700 px-4 py-3">
            <div className="flex items-center gap-2">
              <TeamBadge league={league} abbr={game.away.abbr} />
              <span className="hidden font-display text-xl font-600 text-ink sm:inline">{game.away.name}</span>
              <span className="text-faint">at</span>
              <TeamBadge league={league} abbr={game.home.abbr} />
              <span className="hidden font-display text-xl font-600 text-ink sm:inline">{game.home.name}</span>
            </div>
            <span className="text-sm text-mute">{formatKickoff(game.startTime)}</span>
          </div>

          <nav aria-label="Prop categories" className="-mb-px flex gap-1 overflow-x-auto border-b border-navy-700 px-2">
            {x.categories.map((c) => {
              const on = c.key === x.category.key;
              return (
                <Link
                  key={c.key}
                  href={href(league, { ...x.query, game: game.id }, { cat: c.key })}
                  scroll={false}
                  aria-current={on ? "page" : undefined}
                  className={`shrink-0 whitespace-nowrap border-b-2 px-3 py-2.5 font-display text-[0.95rem] font-600 tracking-wide ${on ? "border-model text-model" : "border-transparent text-mute hover:text-ink"}`}
                >
                  {c.label}
                </Link>
              );
            })}
          </nav>

          <form action="/props" className="flex flex-wrap items-end gap-3 border-b border-navy-700 bg-navy-850 px-4 py-3">
            <input type="hidden" name="sport" value={league} />
            <input type="hidden" name="game" value={game.id} />
            <input type="hidden" name="cat" value={x.category.key} />
            <label className="flex flex-col gap-1 text-[0.7rem] uppercase tracking-wider text-faint">
              Player
              <input name="q" defaultValue={x.query.q ?? ""} placeholder="Search" className="w-40 rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm normal-case tracking-normal text-ink" />
            </label>
            <label className="flex flex-col gap-1 text-[0.7rem] uppercase tracking-wider text-faint">
              Team
              <select name="team" defaultValue={x.query.team ?? ""} className="rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm normal-case tracking-normal text-ink">
                <option value="">Both</option>
                <option value={game.away.abbr}>{game.away.abbr}</option>
                <option value={game.home.abbr}>{game.home.abbr}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[0.7rem] uppercase tracking-wider text-faint">
              Show
              <select name="only" defaultValue={x.query.only ?? ""} className="rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm normal-case tracking-normal text-ink">
                <option value="">All players</option>
                <option value="edges">With an edge</option>
                <option value="strong">Strong edges only</option>
                <option value="ok">Enough history</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[0.7rem] uppercase tracking-wider text-faint">
              Sort
              <select name="sort" defaultValue={x.sort} className="rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 text-sm normal-case tracking-normal text-ink">
                {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </label>
            <button type="submit" className="rounded-full bg-model px-4 py-1.5 text-sm font-600 text-navy-950">Apply</button>
            <AutoSubmit />
          </form>

          <div className="p-3 sm:p-4">
            {isLocked(x.rows) ? (
              <LockedPanel requires={x.rows.requires} title="Player props are part of Plus" body={`Every player's projection, probabilities and exchange comparison for ${x.games.length} upcoming games.`} />
            ) : x.rows.length === 0 ? (
              <p className="px-1 py-6 text-center text-sm text-mute">
                {x.totalPlayers ? "No players match these filters." : `No ${x.category.label.toLowerCase()} projections for this game.`}
              </p>
            ) : (
              <ul className="space-y-2">{x.rows.map((r) => <PlayerRow key={r.id} r={r} league={league} now={x.now} />)}</ul>
            )}
          </div>
        </Panel>
      ) : (
        <Unavailable title="No upcoming games" body="There are no games in the projection window." />
      )}

      <p className="text-xs leading-relaxed text-faint">
        The model never sees exchange prices. Market-implied probability is the midpoint of an exchange&apos;s bid and ask; bid/ask are in cents per $1
        contract. Edges are the expected value of buying at the ask after the exchange fee, from quotes under {x.rules.max_age_min} minutes old with a spread
        under {(x.rules.max_spread * 100).toFixed(0)}¢. Stale, thin or one-sided quotes are struck through and never used. An{" "}
        <strong className="font-600 text-edge">Edge</strong> also needs enough player history, a market type that passed calibration in testing, and published
        size at that price; anything less is a <strong className="font-500 text-mute">Lean</strong>.
      </p>
    </div>
  );
}
