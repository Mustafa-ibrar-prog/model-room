import type { Metadata } from "next";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { connection } from "next/server";
import { Suspense } from "react";
import { Badge } from "@/components/results/ResultCards";
import { PageHeader, Panel, TableSkeleton, Unavailable } from "@/components/ui/primitives";
import { publishedDir } from "@/server/engine/board";
import { ownerLivePropPick } from "@/server/markets/potdLive";
import type { LivePropPick } from "@/server/markets/potdPick";
import type { PickResult } from "@/types/history";

export const metadata: Metadata = { title: "Pick of the Day" };

/**
 * Pick of the Day (TEST): the single strongest disagreement between an active Model Room game model and the
 * pre-kickoff consensus line, one per league per day, frozen once and graded on the stored side and line.
 * Everything shown comes from data/published/pick_of_the_day.json (built by `python -m modelroom potd`).
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
const MARKET: Record<string, string> = { prop: "Player prop", spread: "Spread", total: "Total points", moneyline: "Moneyline" };
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
  if (p.market === "prop") return `${p.projection} ${STAT(p.stat)}`;
  if (p.market === "total") return `${p.projection} pts`;
  return `${p.team} by ${p.projection > 0 ? p.projection : `${p.projection} (loses by ${-p.projection})`}`;
}

export default function PickOfTheDayPage() {
  return (
    <>
      <PageHeader title="Pick of the Day" intro="One player prop per league: Model Room's biggest disagreement with the market line, picked once a day and graded after the game." />
      <Suspense fallback={<div className="mx-auto max-w-5xl px-4 sm:px-6"><TableSkeleton rows={6} /></div>}>
        <Body />
      </Suspense>
    </>
  );
}

async function Body() {
  const f = await load();
  if (!f) return <div className="mx-auto max-w-5xl px-4 sm:px-6"><Unavailable title="Not built yet" body="Today's Pick of the Day appears after the next refresh." /></div>;
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 pb-12 sm:px-6">
      <p className="rounded-lg border border-navy-700 bg-navy-900 px-4 py-3 text-sm leading-relaxed text-mute">{f.notice}</p>
      <div className="grid gap-4 md:grid-cols-2">
        {(["nba", "nfl"] as const).map((lg) => <PickCard key={lg} league={lg} p={f.today[lg]} />)}
      </div>
      <Suspense fallback={null}><OwnerPreview /></Suspense>
      <History f={f} />
      <p className="text-xs leading-relaxed text-faint">
        Qualifies only when the model gives the side at least {pct(f.rule.min_prob)} and at least {(f.rule.min_edge * 100).toFixed(0)} points more
        than the market&apos;s probability (or an even 50% when the line comes without a price). {f.limits} Updated {pt(f.generated_at)}.
      </p>
    </div>
  );
}

function PickCard({ league, p }: { league: "nba" | "nfl"; p: Pick | null }) {
  const title = league.toUpperCase();
  if (!p || p.status !== "pick") {
    return (
      <Panel className="flex min-h-64 flex-col p-5">
        <span className="text-xs font-600 tracking-wide text-faint">{title}</span>
        <h2 className="mt-auto font-display text-2xl font-700 text-ink">No qualifying pick today</h2>
        <p className="mt-2 text-sm text-mute">
          {!p ? "No games left today." : p.reason === "no approved player-prop line source"
            ? "No approved source supplies player-prop lines yet, so there is nothing to compare against. No line is ever estimated."
            : `${p.candidates_considered ?? 0} prop lines checked; none cleared the bar.`}
        </p>
      </Panel>
    );
  }
  return (
    <Panel className="flex flex-col gap-4 p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-600 tracking-wide text-faint">{title} · {MARKET[p.market as string]}</span>
        {p.result !== "none" && p.result !== "pending" ? <Badge result={p.result as PickResult} small /> : <span className="text-xs text-faint">Starts {pt(p.game_start)}</span>}
      </div>
      <div>
        <div className="text-sm text-mute">{p.market === "prop" ? `${p.player} · ${p.team ?? ""} · ` : ""}{p.away} @ {p.home}</div>
        <div className="mt-1 font-display text-3xl font-700 leading-tight text-edge">{sideText(p)}</div>
      </div>
      <dl className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-market/40 bg-navy-900 p-3">
          <dt className="text-xs text-market">Market line</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{lineText(p)}</dd>
          <dd className="mt-0.5 text-xs text-faint">{p.market_prob != null ? `Market ${pct(p.market_prob)}` : p.market === "prop" ? (p.line_source ?? "") : "Consensus, 2+ books"}</dd>
        </div>
        <div className="rounded-lg border border-model/40 bg-navy-900 p-3">
          <dt className="text-xs text-model">Model Room</dt>
          <dd className="mt-1 font-display text-xl font-700 text-ink">{projText(p)}</dd>
          <dd className="mt-0.5 text-xs text-faint">{pct(p.model_prob)} chance{p.difference != null ? ` · ${signed(p.difference)} vs line` : ""}</dd>
        </div>
      </dl>
      <p className="text-sm leading-relaxed text-mute">{p.explanation}</p>
      <p className="text-[0.7rem] leading-snug text-faint">
        Model {p.model_version} · picked {pt(p.selected_at)} · line captured {pt(p.line_captured_at)} · game {pt(p.game_start)}
      </p>
    </Panel>
  );
}

function History({ f }: { f: File }) {
  const rows = f.history.filter((r) => r.status === "pick");
  return (
    <Panel className="p-5">
      <h2 className="font-display text-xl font-700 text-ink">Pick of the Day record</h2>
      <p className="mt-1 text-sm text-mute">Tracked separately from Performance. Unvalidated until {f.rule.unvalidated_until} settled picks per league.</p>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        {(["nba", "nfl"] as const).map((lg) => {
          const r = f.record[lg];
          return (
            <div key={lg} className="rounded-lg bg-navy-900 p-3">
              <div className="text-xs text-faint">{lg.toUpperCase()}</div>
              <div className="mt-1 font-display text-lg font-700 text-ink">{r.hit}–{r.miss}{r.push ? `–${r.push}` : ""}</div>
              <div className="text-xs text-faint">{r.hit_rate == null ? "No graded picks yet" : `${(r.hit_rate * 100).toFixed(0)}% of ${r.graded} graded`} · {r.pending} pending</div>
            </div>
          );
        })}
      </div>
      {rows.length ? (
        <ul className="mt-4 divide-y divide-navy-800">
          {rows.map((r) => (
            <li key={r.pick_key} className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <div className="min-w-0">
                <div className="truncate text-ink">{r.league.toUpperCase()} · {sideText(r)}</div>
                <div className="text-xs text-faint">{r.date} · {r.away} @ {r.home} · {pct(r.model_prob)} · model {r.model_version}</div>
              </div>
              <Badge result={(r.result === "none" ? "pending" : r.result) as PickResult} small />
            </li>
          ))}
        </ul>
      ) : <p className="mt-4 text-sm text-faint">No picks yet.</p>}
    </Panel>
  );
}

async function OwnerPreview() {
  const [nba, nfl] = await Promise.all([ownerLivePropPick("nba"), ownerLivePropPick("nfl")]);
  if (!nba && !nfl) return null;
  return (
    <Panel className="border border-dashed border-market/50 p-5">
      <h2 className="font-display text-lg font-700 text-ink">Owner preview: live Polymarket</h2>
      <p className="mt-1 text-xs leading-relaxed text-faint">
        Only you see this. Fetched live, not stored, not recorded and not graded: Polymarket data can&apos;t be kept or shown publicly until written permission covers it.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {([["NBA", nba], ["NFL", nfl]] as const).map(([lg, r]) => <LiveCard key={lg} league={lg} r={r} />)}
      </div>
    </Panel>
  );
}

function LiveCard({ league, r }: { league: string; r: { pick: LivePropPick | null; checked: number; fetchedAt: string } | null }) {
  if (!r) return null;
  const p = r.pick;
  if (!p) return <div className="rounded-lg bg-navy-900 p-3 text-sm text-mute">{league}: no live prop cleared the bar ({r.checked} Polymarket lines checked).</div>;
  return (
    <div className="rounded-lg bg-navy-900 p-3 text-sm">
      <div className="text-xs text-faint">{league} · {p.player} · {p.matchup} · {pt(p.start)}</div>
      <div className="mt-1 font-display text-xl font-700 text-edge">{p.side === "over" ? "Over" : "Under"} {p.line} {p.label.toLowerCase()}</div>
      <div className="mt-1 text-xs text-mute">
        <span className="text-market">Polymarket {p.contract}+ · {p.side === "over" ? "Yes" : "No"} {(p.price * 100).toFixed(0)}¢ + {(p.fee * 100).toFixed(1)}¢ fee</span>
        {" · "}<span className="text-model">Model {p.projection} · {(p.modelProb * 100).toFixed(0)}%</span> · model {p.modelVersion} · fetched {pt(r.fetchedAt)}
      </div>
    </div>
  );
}
