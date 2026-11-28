"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GameCard, GameOption, LegOption, ParlayPrice, Pick, PropCard } from "@/lib/parlay/types";
import { gameSelection } from "@/lib/parlay/cardMath";
import { Gap, Market, PropRow, SideToggle, useAdd } from "./Picker";
import type { Validation } from "@/server/parlay/validation";

type League = "nba" | "nfl";
type AiState<T> = { status: "ok"; model: string; cached: boolean; text: T } | { status: "unavailable"; reason: string; message: string };
type ParlayAi = { summary: string; legs: { id: string; note: string }[]; riskiest: { id: string; reason: string }[]; watch: string[]; removed: number };
type PicksAi = { overview: string; picks: { id: string; why: string; check: string }[]; removed: number };

import { SLIP_STORE as STORE } from "./Picker";
const pct = (p: number | null | undefined, d = 1) => (p == null ? "–" : `${(p * 100).toFixed(d)}%`);
const odds = (a: number | null | undefined) => (a == null ? "–" : a > 0 ? `+${a}` : `${a}`);
const time = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/Los_Angeles", weekday: "short", hour: "numeric", minute: "2-digit" }) + " PT" : "";

export function ParlayBuilder({ games, asOf, validation, ai, live }: {
  games: Record<League, GameOption[]>;
  asOf: { label: string; at: string | null }[];
  validation: Validation | null;
  ai: { enabled: boolean; model: string; perDay: number };
  live: { on: boolean; pm?: string | null };
}) {
  const [league, setLeague] = useState<League>(games.nba.length || !games.nfl.length ? "nba" : "nfl");
  const [gameId, setGameId] = useState<string | null>(null);
  const [slip, setSlip] = useState<LegOption[]>([]);
  const [price, setPrice] = useState<ParlayPrice | null>(null);
  const [pricing, setPricing] = useState(false);
  const [analysis, setAnalysis] = useState<AiState<ParlayAi> | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  // restore the slip (per-browser convenience only); legs are re-priced on the server, so stale ones drop out
  const restored = useRef(false);
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        const raw = localStorage.getItem(STORE);
        const saved = raw ? (JSON.parse(raw) as LegOption[]) : [];
        if (Array.isArray(saved) && saved.length) setSlip((s) => (s.length ? s : saved.slice(0, 10)));
      } catch {
        /* storage blocked: start empty */
      }
      restored.current = true;
    }, 0);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    if (!restored.current) return; // don't overwrite the saved slip before it has been read
    try {
      localStorage.setItem(STORE, JSON.stringify(slip));
    } catch {
      /* ignore */
    }
  }, [slip]);

  const ids = useMemo(() => slip.map((l) => l.id), [slip]);
  useEffect(() => {
    if (!ids.length) return;
    const ctl = new AbortController();
    const t = setTimeout(() => {
      setPricing(true);
      setAnalysis(null);
      fetch("/api/parlay/price", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ legs: ids }), signal: ctl.signal })
        .then((r) => r.json())
        .then((p: ParlayPrice) => setPrice(p))
        .catch(() => {})
        .finally(() => setPricing(false));
    }, 250);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [ids]);

  const add = useCallback((l: LegOption) => setSlip((s) => (s.some((x) => x.id === l.id) || s.length >= 10 ? s : [...s, l])), []);
  const remove = (id: string) => setSlip((s) => s.filter((x) => x.id !== id));
  const shownPrice = ids.length ? price : null;

  const analyze = async () => {
    setAnalyzing(true);
    try {
      const r = await fetch("/api/parlay/analyze", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ legs: ids }) });
      const j = await r.json();
      if (j.price) setPrice(j.price);
      setAnalysis(j.ai ?? { status: "unavailable", reason: "error", message: "Something went wrong. The numbers above are complete." });
    } catch {
      setAnalysis({ status: "unavailable", reason: "error", message: "Couldn't reach the server. The numbers above are complete." });
    } finally {
      setAnalyzing(false);
    }
  };

  const [more, setMore] = useState(false);
  const withLegs = games[league].filter((g) => g.props || g.lines);
  const list = more ? withLegs : withLegs.slice(0, 12);
  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="min-w-0 space-y-6">
        <LiveBar live={live} />
        <section aria-label="Games">
          <div className="mb-3 flex items-center gap-1" role="tablist" aria-label="League">
            {(["nba", "nfl"] as const).map((lg) => (
              <button key={lg} role="tab" aria-selected={league === lg} onClick={() => { setLeague(lg); setGameId(null); }}
                className={`rounded-md px-3 py-1.5 font-display text-[1.05rem] font-600 tracking-wide ${league === lg ? "bg-navy-800 text-model" : "text-mute hover:text-ink"}`}>
                {lg.toUpperCase()} <span className="text-sm text-faint">{games[lg].filter((g) => g.props || g.lines).length}</span>
              </button>
            ))}
          </div>
          {withLegs.length > 12 ? (
            <button onClick={() => setMore((m) => !m)} className="mb-2 text-sm text-mute hover:text-ink">{more ? "Show fewer games" : `Show all ${withLegs.length} games`}</button>
          ) : null}
          {list.length === 0 ? (
            <p className="rounded-xl border border-navy-700 bg-navy-900 p-5 text-sm text-mute">No upcoming {league.toUpperCase()} games with stored data right now.</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((g) => (
                <li key={g.gameId}>
                  <button onClick={() => setGameId(g.gameId === gameId ? null : g.gameId)} aria-pressed={g.gameId === gameId}
                    className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${g.gameId === gameId ? "border-model bg-navy-800" : "border-navy-700 bg-navy-900 hover:border-navy-600"}`}>
                    <span className="block font-display text-lg font-600 text-ink">{g.label}</span>
                    <span className="block text-xs text-mute">{time(g.start)} · {[g.lines && "game lines", g.props && "player props"].filter(Boolean).join(" + ")}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {gameId ? <GameLegs key={`${league}-${gameId}`} league={league} gameId={gameId} slip={slip} onAdd={add} /> : null}

        <Picks slipIds={ids} onAdd={add} ai={ai} history={validation?.discovery ?? null} />
        <Method validation={validation} asOf={asOf} ai={ai} />
      </div>

      <aside className="lg:sticky lg:top-20 lg:self-start" aria-label="Your parlay">
        <Slip slip={slip} price={shownPrice} pricing={pricing} onRemove={remove} onClear={() => { setSlip([]); setAnalysis(null); }}
          onAnalyze={analyze} analyzing={analyzing} analysis={analysis} ai={ai} />
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------- game legs
type Cards = { props: PropCard[]; games: GameCard[] };
type LegData = { legs: LegOption[]; cards: Cards; injuries: string[]; game?: GameOption };

function GameLegs({ league, gameId, slip, onAdd }: { league: League; gameId: string; slip: LegOption[]; onAdd: (l: LegOption) => void }) {
  const [data, setData] = useState<LegData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [market, setMarket] = useState<string>("Game lines");
  const [q, setQ] = useState("");
  useEffect(() => {
    fetch(`/api/parlay/legs?league=${league}&game=${encodeURIComponent(gameId)}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject((await r.json()).error)))
      .then((d) => setData(d))
      .catch((e) => setError(typeof e === "string" ? e : "Couldn't load this game."));
  }, [league, gameId]);
  const groups = useMemo(() => {
    const g = data?.cards.games.length ? ["Game lines"] : [];
    return [...g, ...new Set((data?.cards.props ?? []).map((c) => c.label))];
  }, [data]);
  const active = groups.includes(market) ? market : groups[0] ?? market;
  if (error) return <p className="rounded-xl border border-navy-700 bg-navy-900 p-5 text-sm text-mute">{error}</p>;
  if (!data) return <p className="rounded-xl border border-navy-700 bg-navy-900 p-5 text-sm text-mute">Loading…</p>;
  const inSlip = new Set(slip.map((l) => l.id));
  const props = data.cards.props
    .filter((c) => c.label === active && (!q || c.playerName.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (b.quotes.length ? 1 : 0) - (a.quotes.length ? 1 : 0) || b.projection - a.projection);
  const add = (l: LegOption) => onAdd(l);
  return (
    <section aria-label="Legs" className="rounded-xl border border-navy-700 bg-navy-900">
      <div className="flex flex-wrap items-center gap-2 border-b border-navy-700 p-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Market">
          {groups.map((g) => (
            <button key={g} role="tab" aria-selected={active === g} onClick={() => setMarket(g)}
              className={`rounded-md px-2.5 py-1 text-sm ${active === g ? "bg-navy-800 font-600 text-ink" : "text-mute hover:text-ink"}`}>{g}</button>
          ))}
        </div>
        {active !== "Game lines" ? (
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a player" aria-label="Find a player"
            className="ml-auto w-full rounded-md border border-navy-600 bg-navy-950 px-2.5 py-1.5 text-sm text-ink placeholder:text-faint sm:w-48" />
        ) : null}
      </div>
      {data.injuries.length ? <p className="border-b border-navy-700 px-3 py-2 text-xs text-pending">Injury report: {data.injuries.slice(0, 6).join(" · ")}</p> : null}
      {active === "Game lines" ? (
        <ul className="divide-y divide-navy-700">
          {data.cards.games.map((c) => <GameRow key={c.kind} c={c} league={league} inSlip={inSlip} onAdd={add} />)}
        </ul>
      ) : props.length === 0 ? (
        <p className="p-4 text-sm text-mute">{q ? "No player by that name in this market." : "Nothing stored for this market yet."}</p>
      ) : (
        <ul className="max-h-[36rem] divide-y divide-navy-700 overflow-y-auto">
          {props.map((c) => <PropRow key={c.key} c={c} league={league} inSlip={inSlip} onAdd={add} />)}
        </ul>
      )}
    </section>
  );
}

/** A market quotes this exact line (a book's own line, or a Polymarket contract, from either team's side). */
const marketAt = (c: GameCard, x: number) =>
  c.books.some((b) => b.line === x) || c.pm.some((p) => p.line !== null && (c.kind === "total" ? p.line === x : (p.team === "home" ? p.line : -p.line) === x));

function GameRow({ c, league, inSlip, onAdd }: { c: GameCard; league: League; inSlip: Set<string>; onAdd: (l: LegOption) => void }) {
  const [side, setSide] = useState<1 | -1>(1);
  const [L, setL] = useState<number | null>(c.consensus);
  const s = useMemo(() => gameSelection(c, L, side), [c, L, side]);
  const added = inSlip.has(s.ids[0]);
  const { busy, err, go } = useAdd(league, onAdd);
  const title = c.kind === "spread" ? "Spread" : c.kind === "total" ? "Total points" : "Moneyline";
  const labels: [string, string] = c.kind === "total" ? ["Over", "Under"] : [c.home, c.away];
  const show = (x: number) => (c.kind === "spread" ? (side > 0 ? x : -x) : x);
  const signed = (x: number) => (c.kind === "spread" && x > 0 ? `+${x}` : `${x}`);
  return (
    <li className="px-3 py-2.5" data-card={`game-${c.kind}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-[9rem] flex-1">
          <p className="text-sm font-600 text-ink">{title}</p>
          <p className="text-xs text-faint">{c.away} @ {c.home}{c.consensus !== null ? ` · consensus ${c.kind === "spread" ? `${c.home} ${signed(c.consensus)}` : c.consensus}` : ""}</p>
        </div>
        <SideToggle value={side} onChange={setSide} labels={labels} name={`${title} side`} />
        {c.kind !== "moneyline" ? (
          <select value={L ?? ""} onChange={(e) => setL(Number(e.target.value))} aria-label={`${title} line`}
            className="rounded-md border border-navy-600 bg-navy-950 px-2 py-1 font-mono text-xs text-ink">
            {c.lines.map((x) => <option key={x} value={x}>{signed(show(x))}{x === c.consensus ? " · consensus" : marketAt(c, x) ? " · market" : " · model"}</option>)}
          </select>
        ) : null}
        <div className="w-14 text-right">
          <p className="font-mono text-sm text-model">{pct(s.p)}</p>
          <p className="text-[0.68rem] text-faint">model</p>
        </div>
        <div className="w-12 text-right">
          <p className="text-sm"><Gap s={s} /></p>
          <p className="text-[0.68rem] text-faint">gap</p>
        </div>
        <button onClick={() => go(s.ids[0])} disabled={added || busy || s.p === null} aria-label={`Add ${s.label}`}
          className="rounded-md border border-navy-600 px-2.5 py-1 text-sm font-600 text-ink hover:border-model disabled:border-navy-700 disabled:text-faint">
          {added ? "Added" : busy ? "…" : "Add"}
        </button>
      </div>
      <div className="mt-1.5 space-y-1">
        <p className="text-[0.75rem] text-mute">{s.label}{s.push ? ` · push ${pct(s.push)}` : ""}</p>
        <Market s={s} pmOn={c.pmFetchedAt !== null} />
        {err ? <p className="text-[0.72rem] text-edge">{err}</p> : null}
      </div>
    </li>
  );
}

function LiveBar({ live }: { live: { on: boolean; pm?: string | null } }) {
  if (!live.on) return null;
  return (
    <p className="rounded-xl border border-navy-700 bg-navy-900 px-4 py-2.5 text-sm text-mute">
      <span className="font-600 text-ink">Live Polymarket US prices</span> next to the model, fetched when the page loads. Not stored.{live.pm ? ` ${live.pm}` : ""}
    </p>
  );
}

// ------------------------------------------------------------------------------------------------- slip
function Slip({ slip, price, pricing, onRemove, onClear, onAnalyze, analyzing, analysis, ai }: {
  slip: LegOption[]; price: ParlayPrice | null; pricing: boolean; onRemove: (id: string) => void; onClear: () => void;
  onAnalyze: () => void; analyzing: boolean; analysis: AiState<ParlayAi> | null; ai: { enabled: boolean; model: string; perDay: number };
}) {
  const rejected = new Map((price?.rejected ?? []).map((r) => [r.id, r.reason]));
  const legIndex = new Map((price?.legs ?? []).map((l, i) => [l.id, i]));
  return (
    <div className="rounded-xl border border-navy-700 bg-navy-900">
      <div className="flex items-center justify-between border-b border-navy-700 px-4 py-3">
        <h2 className="font-display text-xl font-700 text-ink">Your parlay <span className="text-base font-500 text-faint">{slip.length}/10</span></h2>
        {slip.length ? <button onClick={onClear} className="text-sm text-mute hover:text-ink">Clear</button> : null}
      </div>
      {slip.length === 0 ? (
        <p className="p-4 text-sm text-mute">Pick a game and add legs. Mix games and leagues freely.</p>
      ) : (
        <ol className="divide-y divide-navy-700">
          {slip.map((l) => {
            const live = price?.legs[legIndex.get(l.id) ?? -1];
            return (
              <li key={l.id} className="px-4 py-2.5">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm ${rejected.has(l.id) ? "text-faint line-through" : "text-ink"}`}>{l.label}</p>
                    <p className="text-xs text-faint">{live?.gameLabel ?? ""}{rejected.has(l.id) ? ` · ${rejected.get(l.id)}` : ""}</p>
                  </div>
                  <span className="font-mono text-sm text-model">{pct(live?.p ?? l.p)}</span>
                  <button onClick={() => onRemove(l.id)} aria-label={`Remove ${l.label}`} className="px-1 text-faint hover:text-ink">×</button>
                </div>
                {live?.last10 ? <p className="mt-1 text-[0.72rem] text-mute">{live.last10.text} <span className="text-faint">Past results, not the model&apos;s chance.</span></p> : null}
                {live?.polymarket?.implied != null ? <p className="mt-0.5 text-[0.72rem] text-faint">Polymarket {pct(live.polymarket.implied)} (model {live.p - live.polymarket.implied > 0 ? "+" : ""}{((live.p - live.polymarket.implied) * 100).toFixed(1)} pts)</p> : null}
                <p className="mt-0.5 text-[0.72rem] text-faint">{live?.price ? `Best price ${odds(live.price.american)} at ${live.price.bookTitle ?? "a book"}` : live ? live.noPrice ?? "No sportsbook price available" : ""}</p>
                {live?.warnings.length ? <p className="mt-1 text-[0.72rem] leading-snug text-mute">{live.warnings.filter((w) => !w.startsWith("No sportsbook")).join(" ")}</p> : null}
              </li>
            );
          })}
        </ol>
      )}
      {price && slip.length ? <Numbers price={price} pricing={pricing} /> : null}
      {slip.length ? (
        <div className="border-t border-navy-700 p-4">
          <button onClick={onAnalyze} disabled={analyzing || !price?.ok}
            className="w-full rounded-full bg-model px-4 py-2.5 font-600 text-navy-950 disabled:opacity-50">
            {analyzing ? "Analyzing…" : "Analyze My Parlay"}
          </button>
          <p className="mt-2 text-center text-[0.72rem] text-faint">
            {ai.enabled ? `Plain-English notes from ${ai.model}. ${ai.perDay} a day. It explains the numbers; it never changes them.` : "AI notes aren't switched on yet. The numbers work without them."}
          </p>
          {analysis ? <Analysis a={analysis} price={price} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function Numbers({ price, pricing }: { price: ParlayPrice; pricing: boolean }) {
  if (!price.ok) return <p className="border-t border-navy-700 p-4 text-sm text-danger">{price.error}</p>;
  const lo = price.range?.[0] ?? 0;
  const hi = price.range?.[1] ?? 0;
  const scale = Math.max(hi, price.independent ?? 0, price.p ?? 0, 0.02) * 1.15;
  const x = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  return (
    <div className={`border-t border-navy-700 p-4 ${pricing ? "opacity-60" : ""}`} aria-live="polite">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs text-mute">Model chance all legs win</p>
          <p className="font-display text-4xl font-700 leading-none text-model">{price.p === null ? `${pct(lo)}–${pct(hi)}` : pct(price.p)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-mute">Fair odds</p>
          <p className="font-mono text-xl text-ink">{odds(price.fairAmerican)}</p>
        </div>
      </div>
      {/* range bar: the band is the uncertainty; the white tick is the legs multiplied as if unrelated */}
      <div className="relative mt-4 h-3 rounded-full bg-navy-800" aria-hidden="true">
        <div className="absolute inset-y-0 rounded-full bg-model/30" style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }} />
        {price.p !== null ? <div className="absolute inset-y-[-3px] w-1 rounded bg-model" style={{ left: x(price.p) }} /> : null}
        {price.independent !== null ? <div className="absolute inset-y-[-5px] w-0.5 bg-market" style={{ left: x(price.independent) }} /> : null}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-mute">Range</dt><dd className="text-right font-mono text-ink">{pct(lo)} – {pct(hi)}</dd>
        <dt className="text-mute">If legs were unrelated</dt><dd className="text-right font-mono text-market">{pct(price.independent)}</dd>
        <dt className="text-mute">Correlation effect</dt>
        <dd className={`text-right font-mono ${price.correlationEffect == null ? "text-faint" : price.correlationEffect > 1.02 ? "text-good" : price.correlationEffect < 0.98 ? "text-edge" : "text-ink"}`}>
          {price.correlationEffect == null ? "–" : `×${price.correlationEffect.toFixed(2)}`}
        </dd>
        <dt className="text-mute">Books, legs priced separately</dt>
        <dd className="text-right font-mono text-market">{price.bookIfSeparate ? odds(price.bookIfSeparate.american) : "not all priced"}</dd>
      </dl>
      {price.warnings.length ? (
        <ul className="mt-3 space-y-1">
          {price.warnings.map((w, i) => (
            <li key={i} className={`text-[0.8rem] leading-snug ${w.level === "risk" ? "text-danger" : w.level === "caution" ? "text-edge" : "text-mute"}`}>{w.text}</li>
          ))}
        </ul>
      ) : null}
      <p className="mt-3 text-[0.7rem] leading-snug text-faint">{price.method}. Gamble responsibly. 18+/21+ where legal.</p>
    </div>
  );
}

function Analysis({ a, price }: { a: AiState<ParlayAi>; price: ParlayPrice | null }) {
  if (a.status !== "ok") return <p className="mt-3 rounded-lg border border-navy-700 bg-navy-850 p-3 text-sm text-mute">{a.message}</p>;
  const label = (id: string) => price?.legs[Number(id.slice(1)) - 1]?.label ?? id;
  return (
    <div className="mt-3 space-y-3 rounded-lg border border-navy-700 bg-navy-850 p-3 text-sm">
      <p className="text-[0.72rem] text-faint">AI explanation · {a.model}{a.cached ? " · saved answer" : ""} · words only, the numbers come from the model</p>
      {a.text.summary ? <p className="text-ink">{a.text.summary}</p> : null}
      {a.text.riskiest.length ? (
        <div>
          <p className="font-600 text-edge">Riskiest legs</p>
          <ul className="mt-1 space-y-1">{a.text.riskiest.map((r) => <li key={r.id}><span className="text-ink">{label(r.id)}:</span> <span className="text-mute">{r.reason}</span></li>)}</ul>
        </div>
      ) : null}
      {a.text.legs.length ? (
        <ul className="space-y-1">{a.text.legs.map((l) => <li key={l.id}><span className="text-ink">{label(l.id)}:</span> <span className="text-mute">{l.note}</span></li>)}</ul>
      ) : null}
      {a.text.watch.length ? (
        <div>
          <p className="font-600 text-ink">Before the games</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-mute">{a.text.watch.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      ) : null}
      {a.text.removed ? <p className="text-[0.72rem] text-faint">{a.text.removed} sentence{a.text.removed > 1 ? "s" : ""} removed for stating numbers the model didn&apos;t produce.</p> : null}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------- picks
function Picks({ slipIds, onAdd, ai, history }: { slipIds: string[]; onAdd: (l: LegOption) => void; ai: { enabled: boolean; model: string }; history: Validation["discovery"] }) {
  const [picks, setPicks] = useState<Pick[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [review, setReview] = useState<AiState<PicksAi> | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const loaded = useRef(false);
  const load = () => {
    if (loaded.current) return;
    loaded.current = true;
    setLoading(true);
    fetch("/api/parlay/picks").then((r) => r.json()).then((d) => setPicks(d.picks ?? [])).catch(() => setPicks([])).finally(() => setLoading(false));
  };
  const explain = async () => {
    setReviewing(true);
    try {
      const r = await fetch("/api/parlay/picks/review", { method: "POST" });
      const d = await r.json();
      if (d.picks) setPicks(d.picks);
      setReview(d.ai);
    } catch {
      setReview({ status: "unavailable", reason: "error", message: "Couldn't reach the server." });
    } finally {
      setReviewing(false);
    }
  };
  const notes = new Map(review?.status === "ok" ? review.text.picks.map((p) => [p.id, p]) : []);
  return (
    <section aria-label="Picks to consider" className="rounded-xl border border-navy-700 bg-navy-900">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-navy-700 px-4 py-3">
        <div>
          <h2 className="font-display text-xl font-700 text-ink">Picks to consider</h2>
          <p className="text-xs text-mute">Where the model and a stored sportsbook price disagree most. Ranked by the model, not by AI.</p>
        </div>
        {picks === null ? (
          <button onClick={load} className="rounded-md border border-navy-600 px-3 py-1.5 text-sm font-600 text-ink hover:border-model">{loading ? "Loading…" : "Show picks"}</button>
        ) : picks.length && ai.enabled ? (
          <button onClick={explain} disabled={reviewing} className="rounded-md border border-navy-600 px-3 py-1.5 text-sm font-600 text-ink hover:border-model disabled:opacity-50">
            {reviewing ? "Reviewing…" : "Explain with AI"}
          </button>
        ) : null}
      </div>
      {history ? (
        <p className="border-b border-navy-700 px-4 py-2 text-xs text-edge">
          Read this first: {history.summary} The top 3 a week returned {pct(history.top3_roi)} per $1{history.top3_roi_95ci ? ` (range ${pct(history.top3_roi_95ci[0])} to ${pct(history.top3_roi_95ci[1])})` : ""}. A gap is a question, not a value bet.
        </p>
      ) : null}
      {picks !== null && picks.length === 0 ? <p className="p-4 text-sm text-mute">No legs with both a model probability and a stored sportsbook price right now.</p> : null}
      {review && review.status !== "ok" ? <p className="px-4 pt-3 text-sm text-mute">{review.message}</p> : null}
      {review?.status === "ok" && review.text.overview ? <p className="px-4 pt-3 text-sm text-mute"><span className="text-faint">AI ({review.model}, unvalidated): </span>{review.text.overview}</p> : null}
      {picks?.length ? (
        <ol className="divide-y divide-navy-700">
          {picks.map((p, i) => {
            const n = notes.get(`P${i + 1}`);
            return (
              <li key={`${p.benchmark}-${p.leg.id}`} className="px-4 py-3">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-600 text-ink">{p.leg.label}</p>
                    <p className="text-xs text-faint">{p.gameLabel} · data {p.quality} · risk {p.risk}</p>
                  </div>
                  <div className="text-right font-mono text-sm">
                    <span className="text-model">{pct(p.leg.p)}</span> <span className="text-faint">vs {p.benchmark === "polymarket" ? "Polymarket" : "books"}</span> <span className="text-market">{pct(p.marketP)}</span>
                    <p className="text-[0.7rem] text-edge">gap {p.edge == null ? "–" : `${(p.edge * 100).toFixed(1)} pts`}{p.benchmark === "sportsbook" ? ` · ${odds(p.leg.price?.american)}` : ""}</p>
                  </div>
                  <button onClick={() => onAdd(p.leg)} disabled={slipIds.includes(p.leg.id)}
                    className="rounded-md border border-navy-600 px-2.5 py-1 text-sm font-600 text-ink hover:border-model disabled:text-faint">
                    {slipIds.includes(p.leg.id) ? "Added" : "Add"}
                  </button>
                </div>
                <p className="mt-1 text-xs text-mute">{p.why.join(" ")}</p>
                <p className="mt-0.5 text-xs text-faint">Could change it: {p.invalidators.join(" ")}</p>
                {n ? <p className="mt-1 text-xs text-mute"><span className="text-faint">AI note: </span>{[n.why, n.check].filter(Boolean).join(" ")}</p> : null}
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------- method
function Method({ validation, asOf, ai }: { validation: Validation | null; asOf: { label: string; at: string | null }[]; ai: { enabled: boolean; model: string } }) {
  return (
    <details className="rounded-xl border border-navy-700 bg-navy-900 p-4 text-sm">
      <summary className="cursor-pointer font-display text-xl font-700 text-ink">How the numbers are made</summary>
      <div className="mt-3 space-y-3 text-mute">
        <p>Each leg&apos;s chance comes from the same model as the props and game pages. Legs are joined with correlations measured from past box scores: same player, teammates, opponents, and player vs game result and total. Legs in different games are treated as unrelated after testing that on every night of past seasons.</p>
        <p>When there isn&apos;t enough history to measure a link, you get a range that holds whatever the link, not a guess. Sportsbook prices are shown only when stored; nothing is estimated.</p>
        <p>AI ({ai.model}) only explains these numbers in words. It can&apos;t add legs, change a probability or see anything beyond what&apos;s on this page{ai.enabled ? "" : ", and it isn't switched on yet"}.</p>
        {validation?.parlay.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[30rem] text-left text-xs">
              <caption className="mb-1 text-left text-faint">Backtest: random parlays from past games, model chance vs how often they hit</caption>
              <thead><tr className="text-faint"><th className="py-1 font-500">Sample</th><th className="font-500">Parlays</th><th className="font-500">Predicted</th><th className="font-500">Hit</th><th className="font-500">Better than multiplying?</th></tr></thead>
              <tbody>
                {validation.parlay.map((r) => (
                  <tr key={r.label} className="border-t border-navy-700">
                    <td className="py-1.5 text-ink">{r.label}</td><td>{r.parlays.toLocaleString()}</td><td className="font-mono text-model">{pct(r.predicted)}</td><td className="font-mono text-market">{pct(r.hit_rate)}</td>
                    <td>{r.log_loss_gain_95ci && r.log_loss_gain_95ci[0] > 0 ? "Yes (log loss)" : "No clear difference"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <ul className="text-xs text-faint">{asOf.filter((a) => a.at).map((a) => <li key={a.label}>{a.label}: {time(a.at)}</li>)}</ul>
      </div>
    </details>
  );
}
