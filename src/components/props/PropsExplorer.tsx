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
const SUPPORT_LABEL = { ok: null, limited: "Limited history", insufficient: "Thin history" } as const;

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

function EdgeBadge({ l }: { l: PropLineView }) {
  if (l.edge) {
    const strong = l.edge.grade === "strong";
    return (
      <span
        title={strong ? "Strong edge" : `Lean. Not strong: ${l.edge.reasons.join("; ")}`}
        className={`rounded px-1.5 py-0.5 font-mono text-[0.72rem] ${strong ? "bg-edge text-navy-950" : "border border-edge/60 text-edge"}`}
      >
        {strong ? "Strong" : "Lean"} {l.edge.side === "yes" ? "Yes" : "No"} +{(l.edge.ev * 100).toFixed(1)}¢
      </span>
    );
  }
  if (l.market) return <span className="font-mono text-[0.72rem] text-faint">No edge</span>;
  return <span className="font-mono text-[0.72rem] text-faint">{l.quotes.length ? "Unusable price" : "No market"}</span>;
}

function LineCell({ l, highlight }: { l: PropLineView; highlight: boolean }) {
  return (
    <div className={`min-w-[6.5rem] rounded-md border px-2 py-1.5 ${highlight ? "border-model/60 bg-model/5" : "border-navy-700"}`}>
      <div className="font-mono text-[0.72rem] text-mute">{lineLabel(l)}</div>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-lg font-600 text-model">{formatPct(l.modelProb)}</span>
        {l.market?.mid != null ? <span className="font-mono text-xs text-market" title={providerName(l.market.provider)}>{formatPct(l.market.mid)}</span> : null}
      </div>
      <EdgeBadge l={l} />
    </div>
  );
}

function PlayerRow({ r, league }: { r: ExplorerRow; league: League }) {
  const support = SUPPORT_LABEL[r.support];
  return (
    <li className="rounded-lg border border-navy-700 bg-navy-900">
      <div className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(12rem,1.1fr)_minmax(9rem,0.7fr)_2.4fr] md:items-center">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <TeamBadge league={league} abbr={r.team} size="sm" />
            <span className="truncate font-display text-lg font-600 text-ink">{r.name}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-mute">
            <span>{r.position} vs {r.opp}</span>
            {r.injuryStatus ? <span className="text-edge">{r.injuryStatus}</span> : null}
            {support ? <span className="text-faint" title={r.supportNote}>{support}</span> : null}
          </div>
        </div>
        <div>
          <div className="font-display text-2xl font-700 leading-none text-model">{fmt(r.median)}</div>
          <div className="mt-1 font-mono text-[0.7rem] text-faint">
            mean {fmt(r.mean)} · sd {fmt(r.sd)} · 80% {fmt(r.range80[0])}–{fmt(r.range80[1])}
          </div>
        </div>
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1">
          {r.lines.map((l) => <LineCell key={`${l.op}${l.threshold}${l.variant}`} l={l} highlight={l === r.headline} />)}
        </div>
      </div>
      <details className="border-t border-navy-700/70 px-4 py-2">
        <summary className="cursor-pointer text-xs text-faint hover:text-mute">Prices, history and model inputs</summary>
        <div className="grid gap-4 py-2 text-xs md:grid-cols-2">
          <div>
            <h4 className="mb-1 font-mono uppercase tracking-wider text-faint">Exchange prices</h4>
            {r.lines.some((l) => l.quotes.length) ? (
              <ul className="space-y-1">
                {r.lines.flatMap((l) =>
                  l.quotes.map((q, i) => (
                    <li key={`${l.threshold}${l.op}${i}`} className="flex flex-wrap gap-x-2 text-mute">
                      <span className="text-ink">{lineLabel(l)}</span>
                      <span>{providerName(q.provider)}</span>
                      <span className="font-mono">{q.bid != null ? (q.bid * 100).toFixed(0) : "–"}/{q.ask != null ? (q.ask * 100).toFixed(0) : "–"}¢</span>
                      <span>{formatTimestamp(q.capturedAt)}</span>
                      <span className={q.usable ? "text-model" : "text-faint"}>{q.usable ? "usable" : q.flags.join(", ")}</span>
                    </li>
                  )),
                )}
              </ul>
            ) : (
              <p className="text-faint">No exchange lists these lines, or prices aren&apos;t connected.</p>
            )}
          </div>
          <div>
            <h4 className="mb-1 font-mono uppercase tracking-wider text-faint">History behind the estimate</h4>
            <p className="text-mute">{r.supportNote}</p>
            {!isLocked(r.inputs) ? (
              <>
                <h4 className="mb-1 mt-3 font-mono uppercase tracking-wider text-faint">Model inputs</h4>
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
              <p className="mt-3 text-faint">Model inputs (usage, matchup factors) are part of Pro.</p>
            )}
          </div>
        </div>
      </details>
    </li>
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
              <ul className="space-y-2">{x.rows.map((r) => <PlayerRow key={r.id} r={r} league={league} />)}</ul>
            )}
          </div>
        </Panel>
      ) : (
        <Unavailable title="No upcoming games" body="There are no games in the projection window." />
      )}

      <p className="text-xs leading-relaxed text-faint">
        Teal is the model, blue the exchange mid price. Edges use the ask after the exchange fee, from prices under {x.rules.max_age_min} minutes old with a
        spread under {(x.rules.max_spread * 100).toFixed(0)}¢. <strong className="font-500 text-mute">Strong</strong> also needs enough player history, a market type
        that passed calibration in testing, and published size at that price; anything less is a lean.
      </p>
    </div>
  );
}
