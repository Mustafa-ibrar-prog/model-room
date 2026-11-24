"use client";

/**
 * Pick of the Day results dashboard (TEST, Moose 2026-11-24). Reads only the recorded picks and grades passed in from
 * data/published/potd_history.json. The all-time record at the top always covers every recorded pick; tabs, filters and
 * the day view only change the lists below it.
 */
import { useMemo, useState } from "react";
import {
  dayList, facets, filterPicks, pctText, projectedVsActual, record, shiftDate,
  type Filters, type HistFile, type HistPick, type HistResult, type Record,
} from "@/lib/potdHistory";

const STAT = (s: string) => s.replace(/_/g, " ");
const side = (p: HistPick) => `${p.selection === "over" ? "Over" : "Under"} ${p.line} ${STAT(p.stat)}`;
const pct0 = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);
const fmt1 = (x?: number | null) => (x == null ? "—" : Number.isInteger(x) ? String(x) : x.toFixed(1));
const ptTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " PT" : "—";
const longDate = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

const TONE: { [k in HistResult]: string } = {
  win: "bg-good/15 text-good border-good/40",
  loss: "bg-danger/15 text-danger border-danger/40",
  push: "bg-navy-800 text-mute border-navy-600",
  void: "bg-navy-800 text-faint border-navy-600",
  pending: "bg-pending/10 text-pending border-pending/40",
};
const WORD: { [k in HistResult]: string } = { win: "Win", loss: "Loss", push: "Push", void: "Void", pending: "Pending" };

function ResultChip({ r }: { r: HistResult }) {
  return <span className={`inline-flex h-6 min-w-[4.2rem] items-center justify-center rounded-md border px-2 text-[0.7rem] font-700 ${TONE[r]}`}>{WORD[r]}</span>;
}

function WinLossBar({ r }: { r: Record }) {
  const w = r.settled ? (r.win / r.settled) * 100 : 0;
  return (
    <div className="mt-4" aria-hidden={!r.settled}>
      <div className="flex h-3 overflow-hidden rounded-full bg-navy-800" role="img" aria-label={r.settled ? `${r.win} wins and ${r.loss} losses` : "No settled picks yet"}>
        {r.settled ? (
          <>
            <div className="bg-good" style={{ width: `${w}%` }} />
            <div className="bg-danger" style={{ width: `${100 - w}%` }} />
          </>
        ) : null}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-faint">
        <span>{r.settled ? `${w.toFixed(0)}% wins` : "No settled picks yet"}</span>
        <span>{r.settled ? `${(100 - w).toFixed(0)}% losses` : ""}</span>
      </div>
    </div>
  );
}

function Header({ all, f }: { all: Record; f: HistFile }) {
  const need = f.summary.unvalidated_until;
  return (
    <section aria-labelledby="record-h" className="rounded-xl border border-navy-700 bg-navy-900 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="record-h" className="font-display text-xl font-700 text-ink">All-time NBA record</h2>
        <span className="text-xs text-faint">
          {all.settled >= need ? `${all.settled} settled picks` : `Unvalidated: ${all.settled} of ${need} settled picks needed`}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3 sm:gap-6">
        <div>
          <div className="text-xs text-mute">Wins</div>
          <div className="font-display text-4xl font-700 tabular-nums text-good">{all.win}</div>
        </div>
        <div>
          <div className="text-xs text-mute">Losses</div>
          <div className="font-display text-4xl font-700 tabular-nums text-danger">{all.loss}</div>
        </div>
        <div>
          <div className="text-xs text-mute">Win rate</div>
          <div className="font-display text-4xl font-700 tabular-nums text-ink">{pctText(all.winRate)}</div>
        </div>
      </div>
      <WinLossBar r={all} />
      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {[["Settled", all.settled], ["Pending", all.pending], ["Pushes", all.push], ["Voids", all.void]].map(([k, v]) => (
          <div key={k} className="rounded-lg bg-navy-850 px-3 py-2">
            <dt className="text-xs text-faint">{k}</dt>
            <dd className="font-display text-lg font-700 tabular-nums text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-faint">
        Win rate is wins ÷ (wins + losses); pushes, voids and pending picks don&apos;t count. Every pick is frozen before tip-off and graded from the final box score
        at least {f.grading.delay_hours} hours after the game starts. Nothing is estimated or added afterwards.
      </p>
      {all.total === 0 ? (
        <p className="mt-3 rounded-lg border border-navy-700 bg-navy-850 p-3 text-sm text-mute">
          No recorded picks yet. Picks are recorded once an approved line source is in place; the live previews above are never recorded.
        </p>
      ) : null}
    </section>
  );
}

function Detail({ p }: { p: HistPick }) {
  const v = projectedVsActual(p);
  const rows: [string, string][] = [
    ["Matchup", `${p.away ?? "?"} @ ${p.home ?? "?"}`],
    ["Pick", side(p)],
    ["Projection", fmt1(v.projected)],
    ["Final stat", v.actual == null ? (p.result === "void" ? "Did not play" : "Not final yet") : fmt1(v.actual)],
    ["Model probability", pct0(p.model_prob)],
    ...(p.market_prob != null ? [["Market probability", pct0(p.market_prob)] as [string, string]] : []),
    ["Model version", p.model_version],
    ["Frozen", `${ptTime(p.selected_at)}${p.frozen_before_start ? " (before tip-off)" : ""}`],
    ["Tip-off", ptTime(p.game_start)],
    ["Line captured", ptTime(p.line_captured_at)],
    ["Graded", p.grade?.graded_at ? ptTime(p.grade.graded_at) : "Not yet"],
    ["Result source", p.grade?.result_source ?? "—"],
  ];
  return (
    <div className="border-t border-navy-700 bg-navy-850 px-4 py-3">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
        {rows.map(([k, val]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-faint">{k}</dt>
            <dd className="text-right tabular-nums text-ink">{val}</dd>
          </div>
        ))}
      </dl>
      {p.grade?.supersedes != null ? <p className="mt-2 text-xs text-pending">Corrected: {p.grade.reason}</p> : null}
    </div>
  );
}

function PickRow({ p, open, onToggle }: { p: HistPick; open: boolean; onToggle: () => void }) {
  const v = projectedVsActual(p);
  return (
    <li className="overflow-hidden rounded-lg border border-navy-700 bg-navy-900">
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 text-left hover:bg-navy-850 sm:grid-cols-[1fr_8rem_8rem_auto]">
        <div className="min-w-0">
          <div className="truncate text-sm font-600 text-ink">{p.player} <span className="font-400 text-faint">· {p.team ?? ""} vs {p.team === p.home ? p.away : p.home}</span></div>
          <div className="text-xs text-mute">{side(p)} · {longDate(p.date)} · model {p.model_version}</div>
        </div>
        <div className="hidden text-right text-xs text-faint sm:block">
          Projected <span className="font-display text-base font-700 tabular-nums text-ink">{fmt1(v.projected)}</span>
        </div>
        <div className="hidden text-right text-xs text-faint sm:block">
          Actual <span className={`font-display text-base font-700 tabular-nums ${p.result === "win" ? "text-good" : p.result === "loss" ? "text-danger" : "text-ink"}`}>{fmt1(v.actual)}</span>
        </div>
        <ResultChip r={p.result} />
      </button>
      {open ? <Detail p={p} /> : null}
    </li>
  );
}

function PickList({ picks, empty }: { picks: HistPick[]; empty: string }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!picks.length) return <p className="rounded-lg border border-dashed border-navy-700 p-4 text-sm text-faint">{empty}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {picks.map((p) => <PickRow key={p.pick_key} p={p} open={open === p.pick_key} onToggle={() => setOpen(open === p.pick_key ? null : p.pick_key)} />)}
    </ul>
  );
}

const TABS: { key: HistResult | "all"; label: string }[] = [
  { key: "win", label: "Wins" }, { key: "loss", label: "Losses" }, { key: "pending", label: "Pending" }, { key: "all", label: "All" },
];

function Results({ f, all }: { f: HistFile; all: Record }) {
  const [flt, setFlt] = useState<Filters>({ result: "win" });
  const fc = useMemo(() => facets(f.picks), [f.picks]);
  const shown = useMemo(() => filterPicks(f.picks, flt), [f.picks, flt]);
  const count = (k: HistResult | "all") => (k === "all" ? all.total : all[k]);
  const set = (k: keyof Filters, v: string) => setFlt((x) => ({ ...x, [k]: v || undefined }));
  const sel = "rounded-md border border-navy-700 bg-navy-850 px-2 py-1.5 text-sm text-ink";
  return (
    <section aria-labelledby="results-h" className="rounded-xl border border-navy-700 bg-navy-900 p-5">
      <h2 id="results-h" className="font-display text-xl font-700 text-ink">Results</h2>
      <div role="tablist" className="mt-3 flex flex-wrap gap-2">
        {TABS.map((t) => {
          const on = (flt.result ?? "all") === t.key;
          const tone = t.key === "win" ? "text-good" : t.key === "loss" ? "text-danger" : t.key === "pending" ? "text-pending" : "text-ink";
          return (
            <button key={t.key} role="tab" aria-selected={on} type="button" onClick={() => set("result", t.key)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-600 ${on ? "border-navy-600 bg-navy-800" : "border-navy-700 hover:bg-navy-850"}`}>
              <span className={tone}>{t.label}</span> <span className="tabular-nums text-faint">{count(t.key)}</span>
            </button>
          );
        })}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <label className="flex flex-col gap-1 text-xs text-faint">From<input type="date" className={sel} value={flt.from ?? ""} onChange={(e) => set("from", e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs text-faint">To<input type="date" className={sel} value={flt.to ?? ""} onChange={(e) => set("to", e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs text-faint">Player
          <select className={sel} value={flt.player ?? ""} onChange={(e) => set("player", e.target.value)}>
            <option value="">All players</option>{fc.players.map((x) => <option key={x}>{x}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-faint">Stat
          <select className={sel} value={flt.stat ?? ""} onChange={(e) => set("stat", e.target.value)}>
            <option value="">All stats</option>{fc.stats.map((x) => <option key={x} value={x}>{STAT(x)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-faint">Model version
          <select className={sel} value={flt.version ?? ""} onChange={(e) => set("version", e.target.value)}>
            <option value="">All versions</option>{fc.versions.map((x) => <option key={x}>{x}</option>)}
          </select>
        </label>
      </div>
      <p className="mb-3 mt-3 text-xs text-faint">
        Showing {shown.length} of {all.total} recorded picks. Filters change this list only; the record above always covers every settled pick.
      </p>
      <PickList picks={shown} empty={all.total ? "No recorded picks match these filters." : "No recorded picks yet."} />
    </section>
  );
}

function Daily({ f }: { f: HistFile }) {
  const days = useMemo(() => dayList(f), [f]);
  const [date, setDate] = useState(f.today);
  const picks = useMemo(() => f.picks.filter((p) => p.date === date), [f.picks, date]);
  const r = record(picks);
  const info = f.days.find((d) => d.date === date);
  const oldest = days[days.length - 1] ?? f.today;
  const btn = "rounded-md border border-navy-700 px-3 py-1.5 text-sm text-ink hover:bg-navy-850 disabled:opacity-40";
  const label = date === f.today ? "Today" : date === shiftDate(f.today, -1) ? "Yesterday" : longDate(date);
  return (
    <section aria-labelledby="daily-h" className="rounded-xl border border-navy-700 bg-navy-900 p-5">
      <h2 id="daily-h" className="font-display text-xl font-700 text-ink">Daily results</h2>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className={btn} onClick={() => setDate(shiftDate(date, -1))} disabled={date <= oldest} aria-label="Previous day">‹</button>
        <span className="min-w-[10rem] text-center font-display text-lg font-700 text-ink">{label}</span>
        <button type="button" className={btn} onClick={() => setDate(shiftDate(date, 1))} disabled={date >= f.today} aria-label="Next day">›</button>
        <button type="button" className={btn} onClick={() => setDate(f.today)}>Today</button>
        <button type="button" className={btn} onClick={() => setDate(shiftDate(f.today, -1))}>Yesterday</button>
        <input type="date" aria-label="Pick a date" className="rounded-md border border-navy-700 bg-navy-850 px-2 py-1.5 text-sm text-ink"
          min={oldest} max={f.today} value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-2 text-sm sm:grid-cols-5">
        {([["Wins", r.win, "text-good"], ["Losses", r.loss, "text-danger"], ["Pushes", r.push, "text-ink"], ["Pending", r.pending, "text-pending"],
          ["Win rate", pctText(r.winRate), "text-ink"]] as [string, string | number, string][]).map(([k, v, t]) => (
          <div key={k} className="rounded-lg bg-navy-850 px-3 py-2">
            <dt className="text-xs text-faint">{k}</dt>
            <dd className={`font-display text-lg font-700 tabular-nums ${t}`}>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3">
        <PickList picks={picks} empty={info?.reason ? `No recorded pick this day: ${info.reason}.` : date < oldest ? "Before the recorded history starts." : "No recorded picks this day."} />
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm text-mute">All recorded days ({days.length})</summary>
        <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
          {days.map((d) => {
            const dr = record(f.picks.filter((p) => p.date === d));
            return (
              <li key={d}>
                <button type="button" onClick={() => setDate(d)} className={`flex w-full justify-between rounded-md px-3 py-1.5 text-left text-sm hover:bg-navy-850 ${d === date ? "bg-navy-800" : ""}`}>
                  <span className="text-ink">{longDate(d)}</span>
                  <span className="tabular-nums">
                    {dr.total ? <><span className="text-good">{dr.win}</span><span className="text-faint">–</span><span className="text-danger">{dr.loss}</span>{dr.pending ? <span className="text-pending"> · {dr.pending} pending</span> : null}</> : <span className="text-faint">No pick</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </details>
    </section>
  );
}

export function ResultsDashboard({ f }: { f: HistFile }) {
  const all = useMemo(() => record(f.picks), [f.picks]);
  return (
    <div className="flex flex-col gap-4">
      <Header all={all} f={f} />
      <Results f={f} all={all} />
      <Daily f={f} />
    </div>
  );
}
