import type { Metadata } from "next";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { connection } from "next/server";
import { Suspense, type ReactNode } from "react";
import { Badge } from "@/components/results/ResultCards";
import { PageHeader, Panel, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import { formatProjection } from "@/lib/format";
import { publishedDir } from "@/server/engine/board";
import { livePropPick, potdLiveStatus, type LiveResult } from "@/server/markets/potdLive";
import { MIN_EDGE, MIN_PROB, RELIABILITY, type LivePropPick } from "@/server/markets/potdPick";
import type { PickResult } from "@/types/history";

export const metadata: Metadata = { title: "Pick of the Day" };

/**
 * NBA Pick of the Day (TEST). NBA player props only (Moose, 2026-11-22): NFL is not shown or selected.
 * Live card: the most reliable qualifying prop from the active NBA model against live Polymarket US prices, fetched at
 * request time, never stored, recorded or graded. Recorded picks and grades come from data/published/pick_of_the_day.json
 * (`python -m modelroom potd --league nba`); the ledger is never edited.
 */
type Pick = {
  pick_key: string; date: string; league: "nba" | "nfl"; status: "pick" | "no_pick"; market?: "prop" | "spread" | "total" | "moneyline";
  format?: string; reason?: string; stat?: string; player?: string;
  selection?: string; team?: string | null; home?: string; away?: string; line?: number | null; price?: number | null;
  model_prob?: number; market_prob?: number | null; reference_prob?: number; edge?: number; projection?: number | null;
  difference?: number | null; explanation?: string; model_version?: string; selected_at: string; game_start?: string;
  line_source?: string | null; line_captured_at?: string | null; candidates_considered?: number; games_with_lines?: number;
  result: PickResult | "none";
};
type Rec = { hit: number; miss: number; push: number; void: number; pending: number; graded: number; hit_rate: number | null; note: string };
type File = { generated_at: string; date: string; today: Record<"nba" | "nfl", Pick | null>; history: Pick[]; record: Record<"nba" | "nfl", Rec>;
  rule: { min_prob: number; min_edge: number; unvalidated_until: number }; notice: string; limits: string };

async function load(): Promise<File | null> {
  await connection();
  try {
    return JSON.parse(await readFile(path.join(publishedDir(), "pick_of_the_day.json"), "utf8")) as File;
  } catch {
    return null;
  }
}

const pt = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " PT" : "—";
const pct = (p?: number | null) => (p == null ? null : `${(p * 100).toFixed(0)}%`);
const signed = (n: number) => (n > 0 ? `+${n}` : `${n}`);
const signedWhole = (n: number) => signed(Number(formatProjection(n))); // player projection gaps: whole numbers
const STAT = (s?: string) => (s ?? "").replace(/_/g, " ").replace("anytime td", "touchdowns").replace("passing tds", "passing TDs");

function sideText(p: Pick): string {
  if (p.market === "prop") return `${p.selection === "over" ? "Over" : "Under"} ${p.line} ${STAT(p.stat)}`;
  if (p.market === "total") return `${p.selection === "over" ? "Over" : "Under"} ${p.line}`;
  if (p.market === "spread") return `${p.team} ${signed(p.line as number)}`;
  return `${p.team} to win`;
}

function lineText(p: Pick): string {
  if (p.market === "prop") return `${p.line}`;
  if (p.market === "moneyline") return p.price == null ? "—" : signed(p.price);
  if (p.market === "spread") return `${p.team} ${signed(p.line as number)}`;
  return `${p.line}`;
}

function projText(p: Pick): string {
  if (p.projection == null) return "—";
  if (p.market === "prop") return `${formatProjection(p.projection)} ${STAT(p.stat)}`;
  if (p.market === "total") return `${p.projection} pts`;
  return `${p.team} by ${p.projection > 0 ? p.projection : `${p.projection} (loses by ${-p.projection})`}`;
}

export default function PickOfTheDayPage() {
  return (
    <>
      <PageHeader title="Pick of the Day" intro="Every NBA player prop that qualifies today under Model Room's NBA model, checked against live Polymarket prices and listed from most to least reliable." />
      <Suspense fallback={<div className="mx-auto max-w-5xl px-4 sm:px-6"><TableSkeleton rows={6} /></div>}>
        <Body />
      </Suspense>
    </>
  );
}

async function Body() {
  const f = await load();                                  // load() awaits connection(): request time before any clock read
  const live = await livePropPick();
  const status = potdLiveStatus();
  const today = f?.today?.nba ?? null;
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 pb-12 sm:px-6">
      <p className="rounded-lg border border-navy-700 bg-navy-900 px-4 py-3 text-sm leading-relaxed text-mute">
        Unvalidated. Model Room hasn&apos;t shown an edge against the market yet. These are the NBA props that qualify under the model&apos;s rules, not guaranteed results and not betting advice.
      </p>
      {live ? <LiveCard r={live} /> : f ? <PickCard p={today} liveOff={status.on ? null : status.reason} /> : <Unavailable title="Not built yet" body="Today's Pick of the Day appears after the next refresh." />}
      {f ? <History f={f} /> : null}
      <Rules />
    </div>
  );
}

function Rules() {
  return (
    <p className="text-xs leading-relaxed text-faint">
      How a pick qualifies: each player and stat is judged only at its main line, the Polymarket contract priced closest to 50¢; other
      ladder rungs never compete. The model&apos;s probability for the side is then adjusted for reliability. That adjustment was fitted on 2023–24 and tested on the
      next two seasons, and it marks a pick down when more of its projection comes from blowout, matchup or usage adjustments than from the player&apos;s own
      baseline. The adjusted probability must reach {(MIN_PROB * 100).toFixed(1)}% and beat the Polymarket price plus fees by at least {(MIN_EDGE * 100).toFixed(0)} points.
      Every prop that clears both bars is listed, from the highest adjusted probability down; there is no fixed number, and
      the size of the gap with the market is never the ranking. Lines and prices come from Polymarket US at the moment the page loads; none
      are estimated, stored or graded. Model {RELIABILITY.model} is the active NBA model; shadow versions are never used for picks until approved.
    </p>
  );
}

function NoPick({ reason, children, tag }: { reason: string; children?: ReactNode; tag?: ReactNode }) {
  return (
    <Panel className="flex min-h-56 flex-col gap-2 p-5">
      <div className="flex items-center justify-between gap-2"><span className="text-xs font-600 tracking-wide text-faint">NBA · Player prop</span>{tag}</div>
      <h2 className="mt-auto font-display text-2xl font-700 text-ink">No qualifying NBA pick today</h2>
      <p className="text-sm text-mute">{reason}</p>
      {children}
    </Panel>
  );
}

function PickCard({ p, liveOff }: { p: Pick | null; liveOff: string | null }) {
  if (!p || p.status !== "pick") {
    return (
      <NoPick reason={!p ? "No NBA games left today." : p.reason === "no approved player-prop line source"
        ? "No approved source supplies player-prop lines for recorded picks, so nothing is recorded. No line is ever estimated."
        : `${p.candidates_considered ?? 0} prop lines checked; none cleared the bar.`}>
        {liveOff && liveOff !== "off in production" ? <p className="text-xs leading-relaxed text-faint">Live Polymarket comparison is off: {liveOff}.</p> : null}
      </NoPick>
    );
  }
  return (
    <Panel className="flex flex-col gap-4 p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-600 tracking-wide text-faint">NBA · Recorded pick</span>
        {p.result !== "none" && p.result !== "pending" ? <Badge result={p.result as PickResult} small /> : <span className="text-xs text-faint">Starts {pt(p.game_start)}</span>}
      </div>
      <div>
        <div className="text-sm text-mute">{p.player} · {p.team ?? ""} · {p.away} @ {p.home}</div>
        <div className="mt-1 font-display text-3xl font-700 leading-tight text-edge">{sideText(p)}</div>
      </div>
      <dl className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-market/40 bg-navy-900 p-3">
          <dt className="text-xs text-market">Market line</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{lineText(p)}</dd>
          <dd className="mt-0.5 text-xs text-faint">{p.market_prob != null ? `Market ${pct(p.market_prob)}` : (p.line_source ?? "")}</dd>
        </div>
        <div className="rounded-lg border border-model/40 bg-navy-900 p-3">
          <dt className="text-xs text-model">Model Room</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{projText(p)}</dd>
          <dd className="mt-0.5 text-xs text-faint">{pct(p.model_prob)} chance{p.difference != null ? ` · ${signedWhole(p.difference)} vs line` : ""}</dd>
        </div>
      </dl>
      <p className="text-sm leading-relaxed text-mute">{p.explanation}</p>
      <p className="text-[0.7rem] leading-snug text-faint">Model {p.model_version} · picked {pt(p.selected_at)} · line captured {pt(p.line_captured_at)} · game {pt(p.game_start)}</p>
    </Panel>
  );
}

function History({ f }: { f: File }) {
  const rows = f.history.filter((r) => r.status === "pick" && r.league === "nba");
  const r = f.record.nba;
  return (
    <Panel className="p-5">
      <h2 className="font-display text-xl font-700 text-ink">Recorded NBA picks</h2>
      <p className="mt-1 text-sm text-mute">
        Only picks frozen before tip-off and graded after the game count here. Live Polymarket previews are never recorded, so they never appear in this record.
      </p>
      <div className="mt-3 rounded-lg bg-navy-900 p-3 text-sm">
        <div className="font-display text-lg font-700 text-ink">{r ? `${r.hit}–${r.miss}${r.push ? `–${r.push}` : ""}` : "0–0"}</div>
        <div className="text-xs text-faint">{!r || r.hit_rate == null ? "No graded picks yet" : `${(r.hit_rate * 100).toFixed(0)}% of ${r.graded} graded`}{r ? ` · ${r.pending} pending` : ""} · unvalidated until {f.rule.unvalidated_until} settled picks</div>
      </div>
      {rows.length ? (
        <ul className="mt-4 divide-y divide-navy-800">
          {rows.map((x) => (
            <li key={x.pick_key} className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <div className="min-w-0">
                <div className="truncate text-ink">{x.player ? `${x.player} · ` : ""}{sideText(x)}</div>
                <div className="text-xs text-faint">{x.date} · {x.away} @ {x.home} · {pct(x.model_prob)} · model {x.model_version}</div>
              </div>
              <Badge result={(x.result === "none" ? "pending" : x.result) as PickResult} small />
            </li>
          ))}
        </ul>
      ) : <p className="mt-4 text-sm text-faint">No recorded NBA picks yet.</p>}
    </Panel>
  );
}

function listed(xs: { name: string; status: string }[]): string {
  return xs.length ? xs.map((x) => `${x.name} (${x.status.toLowerCase()})`).join(", ") : "nobody listed";
}

function histText(p: LivePropPick): string {
  const h = p.history, n = p.contract, lbl = p.label.toLowerCase();
  const parts: string[] = [];
  if (h.thisSeason) parts.push(`in ${h.thisSeason.hits} of ${h.thisSeason.games} games this season (${Math.round((h.thisSeason.hits / h.thisSeason.games) * 100)}%)`);
  if (h.lastSeason) parts.push(`in ${h.lastSeason.hits} of ${h.lastSeason.games} games last season (${Math.round((h.lastSeason.hits / h.lastSeason.games) * 100)}%)`);
  return parts.length ? `He has reached ${n}+ ${lbl} ${parts.join(" and ")}.` : `Too few games this season or last to show how often he reaches ${n}+ ${lbl}.`;
}

/** Projection against the line, signed, one decimal: "0.2 below the line". */
function vsLine(d: number): string {
  if (Math.abs(d) < 0.05) return "on the line";
  return `${Math.abs(d).toFixed(1)} ${d > 0 ? "above" : "below"} the line`;
}
const avg = (x: number) => x.toFixed(1);

/** His own entry in the live injury report (official first, ESPN otherwise), never inferred. */
function ownStatus(p: LivePropPick): string {
  if (!p.injuries) return "unavailable";
  const e = p.injuries.team.find((x) => x.name === p.player);
  return e ? `listed ${e.status.toLowerCase()}` : "he is not listed as out, doubtful or questionable";
}

const TAG = <span className="rounded border border-dashed border-market/60 px-1.5 py-0.5 text-[0.65rem] text-market">TEST · live preview · not recorded</span>;
const p1 = (x: number) => `${(x * 100).toFixed(1)}%`;

function LiveCard({ r }: { r: LiveResult }) {
  if (!r.picks.length) {
    return (
      <NoPick reason={r.reason} tag={TAG}>
        {r.rejected.length ? (
          <div className="mt-1 text-xs text-faint">
            <div className="font-600 text-mute">Closest candidates, and why they didn&apos;t qualify</div>
            <ul className="mt-1 space-y-1">
              {r.rejected.map((x, i) => (
                <li key={i}>{x.player} ({x.team}) {x.side === "over" ? "Over" : "Under"} {x.line} {x.label.toLowerCase()}: {x.why}.</li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="text-[0.7rem] text-faint">{r.games} games today · {r.found} on Polymarket · {r.diag?.lines ?? 0} main lines · {r.checked} checked · model {r.modelVersion ?? "—"} · updated {pt(r.fetchedAt)}</p>
      </NoPick>
    );
  }
  const rank = new Map(r.picks.map((p, i) => [p, i + 1]));
  const games: { id: string; picks: LivePropPick[] }[] = [];
  for (const p of r.picks) {
    const g = games.find((x) => x.id === p.gameId);
    if (g) g.picks.push(p);
    else games.push({ id: p.gameId, picks: [p] });
  }
  const byPlayer = new Map<string, number[]>();
  for (const p of r.picks) byPlayer.set(p.player, [...(byPlayer.get(p.player) ?? []), rank.get(p)!]);
  const repeats = [...byPlayer].filter(([, v]) => v.length > 1);
  return (
    <div className="space-y-5">
      <div className="text-sm text-mute">
        <p>
          {r.picks.length === 1 ? "1 NBA prop qualifies today" : `${r.picks.length} NBA props qualify today`} across {games.length === 1 ? "1 game" : `${games.length} games`}, numbered from most to least reliable.
          Each is judged at its main line; nothing is forced to fill a slot.
        </p>
        {games.length === 1 && r.picks.length > 1 ? <p className="mt-1 text-xs text-faint">All of today&apos;s qualifying props come from the same game, so their results are linked.</p> : null}
        {repeats.length ? <p className="mt-1 text-xs text-faint">More than one prop for the same player: {repeats.map(([n, v]) => `${n} (#${v.join(", #")})`).join("; ")}.</p> : null}
      </div>
      {games.map((g) => <GameGroup key={g.id} picks={g.picks} rank={rank} byPlayer={byPlayer} />)}
      <p className="text-[0.7rem] leading-snug text-faint">
        Model {r.modelVersion} (active) · reliability {RELIABILITY.id} · projections {pt(r.boardAt)} · prices {pt(r.fetchedAt)} · {r.checked} main lines checked
      </p>
    </div>
  );
}

function GameGroup({ picks, rank, byPlayer }: { picks: LivePropPick[]; rank: Map<LivePropPick, number>; byPlayer: Map<string, number[]> }) {
  const f = picks[0];
  const gm = f.game;
  const home = gm?.home, away = gm?.away;
  const inj = f.injuries;
  const injFor = (abbr?: string) => (!inj || !abbr ? null : abbr === f.team ? inj.team : abbr === f.opp ? inj.opp : null);
  return (
    <section className="space-y-3">
      <Panel className="p-4 text-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-display text-xl font-700 text-ink">{f.matchup}</h2>
          <span className="text-xs text-faint">{pt(f.start)} · {picks.length === 1 ? "1 qualifying prop" : `${picks.length} qualifying props`} in this game</span>
        </div>
        {gm ? (
          <p className="mt-2 text-mute">
            Game model {gm.model}: {gm.away} {Math.round(gm.awayScore)}, {gm.home} {Math.round(gm.homeScore)} ({gm.favored} by {Math.abs(gm.margin).toFixed(1)}), total {Math.round(gm.total)}{gm.pace ? `, pace ${Math.round(gm.pace)}` : ""}.
            Chance either team wins by 10+: {Math.round(gm.p10 * 100)}%, by 15+: {Math.round(gm.p15 * 100)}%, by 20+: {Math.round(gm.p20 * 100)}%.
          </p>
        ) : <p className="mt-2 text-faint">Game projection unavailable for this game.</p>}
        {gm ? <p className="mt-1 text-xs text-faint">From the game model&apos;s projected margin and its measured error ({gm.sigma.toFixed(1)} points), not the betting spread. In model {f.modelVersion}, the margin affects props only through the blowout minutes step shown on a card.</p> : null}
        <h3 className="mt-3 text-sm font-600 text-ink">Context the model does not use</h3>
        <ul className="mt-1 space-y-1 leading-relaxed text-mute">
          <li>
            {inj ? <>Injury report ({inj.source}{inj.reportTime ? `, ${pt(inj.reportTime)}` : ""}): {away ?? f.team} {listed(injFor(away) ?? [])}; {home ?? f.opp} {listed(injFor(home) ?? [])}. Model {f.modelVersion} does not read the report, so players listed out may still be in its projections.</> : "Injury report unavailable."}
          </li>
          <li>Individual defenders: unavailable (no free, licensed source of defensive assignments; never guessed). Starting lineups: projected from recent starts only.</li>
        </ul>
      </Panel>
      {picks.map((p) => <LiveOpportunity key={`${p.gameId}-${p.player}-${p.stat}`} p={p} rank={rank.get(p)!} others={(byPlayer.get(p.player) ?? []).filter((x) => x !== rank.get(p))} />)}
    </section>
  );
}

function LiveOpportunity({ p, rank, others }: { p: LivePropPick; rank: number; others: number[] }) {
  const lbl = p.label.toLowerCase();
  return (
    <Panel className="flex flex-col gap-3 p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3"><span className="text-xs font-600 tracking-wide text-faint">#{rank} · NBA player prop</span>{TAG}</div>
      <div>
        <div className="text-sm text-mute">{p.player} ({p.team}) vs {p.opp}{others.length ? ` · also #${others.join(", #")}` : ""}</div>
        <div className="mt-1 font-display text-2xl font-700 leading-tight text-edge sm:text-3xl">{p.side === "over" ? "Over" : "Under"} {p.line} {lbl}</div>
      </div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
        <div className="rounded-lg border border-model/40 bg-navy-900 p-2.5 sm:p-3">
          <dt className="text-xs text-model">Projection</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{formatProjection(p.projection)} {lbl}</dd>
          <dd className="mt-0.5 text-xs text-faint">{vsLine(p.difference)}</dd>
        </div>
        <div className="rounded-lg border border-model/40 bg-navy-900 p-2.5 sm:p-3">
          <dt className="text-xs text-model">Model probability</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{p1(p.adjProb)}</dd>
          <dd className="mt-0.5 text-xs text-faint">{p1(p.modelProb)} before reliability</dd>
        </div>
        <div className="rounded-lg border border-market/40 bg-navy-900 p-2.5 sm:p-3">
          <dt className="text-xs text-market">Market probability</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{p1(p.marketProb)}</dd>
          <dd className="mt-0.5 text-xs text-faint">{p.contract}+ {p.side === "over" ? "Yes" : "No"} {(p.price * 100).toFixed(0)}¢ + {(p.fee * 100).toFixed(1)}¢ fee</dd>
        </div>
        <div className="rounded-lg border border-edge/40 bg-navy-900 p-2.5 sm:p-3">
          <dt className="text-xs text-edge">Edge after fees</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{(p.edge * 100).toFixed(1)} pts</dd>
          <dd className="mt-0.5 text-xs text-faint">vs {(p.cost * 100).toFixed(1)}¢ cost</dd>
        </div>
      </dl>
      <div>
        <h3 className="text-sm font-600 text-ink">What moved the projection (model {p.modelVersion})</h3>
        {p.factors.length ? (
          <ul className="mt-1 space-y-1 text-sm leading-relaxed text-mute">
            {p.factors.map((x) => (
              <li key={x.key}>
                {x.text} <span className={x.favors === "pick" ? "text-edge" : "text-market"}>({x.favors === "pick" ? "toward" : "against"} the {p.side === "over" ? "Over" : "Under"})</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-1 text-sm text-mute">Nothing beyond his own rates and usual minutes: no adjustment moved it by 0.05 or more.</p>}
      </div>
      <div className="text-sm">
        <h3 className="text-sm font-600 text-ink">About this line</h3>
        <ul className="mt-1 space-y-1 leading-relaxed text-mute">
          <li>Main line: {p.line} is the {lbl} contract priced closest to 50¢ for him. {histText(p)}</li>
          <li>
            Averages: {p.form.seasonAvg != null ? `${avg(p.form.seasonAvg)} ${lbl} this season (${p.form.seasonGames} games)` : "no games this season yet"}{p.form.last5 != null ? `, ${avg(p.form.last5)} over his last 5` : ""}.
            Minutes: {p.minutes.projected != null ? `${p.minutes.projected.toFixed(1)} projected` : "projection unavailable"}{p.minutes.usual != null ? `, ${p.minutes.usual.toFixed(1)} usual` : ""}; fourth-quarter minutes are not modeled.
          </li>
          <li>Reliability: {p.toward > 0.005 ? `${Math.round(p.toward * 100)}% of the projection comes from adjustments toward this side, so its probability is marked down from ${p1(p.modelProb)} to ${p1(p.adjProb)}.` : `the projection rests on his own baseline; the standard reliability adjustment takes it from ${p1(p.modelProb)} to ${p1(p.adjProb)}.`} Model history: {p.support}.</li>
          <li>Injury report: {ownStatus(p)} (context only; model {p.modelVersion} does not read the report).</li>
        </ul>
      </div>
    </Panel>
  );
}
