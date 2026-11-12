"use client";

/**
 * Recent performance, chosen by the reader: Last 5 / Last 10 / Season / Game log.
 * Shows only games the board published: never pads a short history, and labels games from an earlier season.
 * Per-game results (the stat) and opportunity (minutes, attempts, snaps, targets) are kept in separate blocks.
 * Display only: the model never reads these numbers.
 */
import { useState } from "react";

export interface HistoryTabsData {
  stat: string;
  games: { date: string; opp: string; season: number | null; value: number | null; opp_: Record<string, number | null> }[];
  published: number;
  boardSeason: number;
  seasonText: string;
  season: { games: number; avg: number | null; opportunity: Record<string, number> } | null;
  opportunity: { key: string; label: string }[];
  /** "k or more" threshold the games are checked against, and its label ("Over 23.5"); null without a line. */
  clear: { k: number; op: ">=" | ">"; label: string } | null;
  /** Labels for seasons other than the board's (e.g. 2027 → "2026–27"). */
  seasonNames: Record<number, string>;
}

const TABS = ["Last 5", "Last 10", "Season", "Game log"] as const;

const f1 = (n: number) => (Number.isInteger(n) || Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1));
const day = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[0.68rem] text-faint">{label}</div>
      <div className="font-mono text-lg leading-tight text-ink">{value}</div>
      {sub ? <div className="text-[0.65rem] text-faint">{sub}</div> : null}
    </div>
  );
}

function OppBlock({ title, items }: { title: string; items: { label: string; value: number | null }[] }) {
  const shown = items.filter((i) => i.value != null);
  if (!shown.length) return null;
  return (
    <div className="rounded-md bg-navy-850 px-3 py-2">
      <div className="text-[0.68rem] text-faint">{title}</div>
      <dl className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
        {shown.map((i) => (
          <div key={i.label} className="flex gap-1.5"><dt className="text-mute">{i.label}</dt><dd className="font-mono text-ink">{f1(i.value!)}</dd></div>
        ))}
      </dl>
    </div>
  );
}

export function HistoryTabs({ d }: { d: HistoryTabsData }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Last 5");
  const clears = (v: number | null) => (v == null || !d.clear ? null : d.clear.op === ">=" ? v >= d.clear.k : v > d.clear.k);
  const played = d.games.filter((g) => g.value != null);
  const other = (g: { season: number | null }) => g.season != null && g.season !== d.boardSeason;

  const windowView = (n: number) => {
    const gs = played.slice(0, n);
    if (!gs.length) return <p className="text-sm text-mute">No past games on record for this player.</p>;
    const avg = gs.reduce((a, g) => a + g.value!, 0) / gs.length;
    const hits = d.clear ? gs.filter((g) => clears(g.value)).length : null;
    const older = gs.filter(other);
    const max = Math.max(...gs.map((g) => g.value!), d.clear ? d.clear.k : 0, 1);
    const ordered = [...gs].reverse();
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Stat label={`${d.stat}, per game`} value={f1(avg)} sub={`${gs.length} game${gs.length === 1 ? "" : "s"}`} />
          {d.clear ? <Stat label={d.clear.label} value={`${hits} of ${gs.length}`} sub="games that cleared it" /> : <Stat label="Market line" value="–" sub="none to compare" />}
          <Stat label="Range" value={`${f1(Math.min(...gs.map((g) => g.value!)))}–${f1(Math.max(...gs.map((g) => g.value!)))}`} sub="low to high" />
        </div>
        <figure className="m-0" role="img" aria-label={`${d.stat} in the last ${gs.length} games, oldest first`}>
          <div className="relative flex h-24 items-end gap-1">
            {ordered.map((g) => (
              <div key={g.date} className="flex h-full flex-1 flex-col items-center justify-end gap-0.5" title={`${day(g.date)} vs ${g.opp}: ${g.value}`}>
                <span className="font-mono text-[0.62rem] text-mute">{f1(g.value!)}</span>
                <span className={`w-full rounded-t-sm ${clears(g.value) ? "bg-model" : "bg-navy-600"} ${other(g) ? "opacity-60" : ""}`} style={{ height: `${Math.max(3, (g.value! / max) * 78)}%` }} />
              </div>
            ))}
            {d.clear ? <span className="pointer-events-none absolute inset-x-0 border-t border-dashed border-ink/70" style={{ bottom: `${(d.clear.k / max) * 78}%` }} aria-hidden="true" /> : null}
          </div>
          <div className="mt-1 flex gap-1 text-center text-[0.6rem] text-faint">
            {ordered.map((g) => <span key={g.date} className="flex-1 truncate">{g.opp}</span>)}
          </div>
          <figcaption className="mt-1 text-[0.68rem] text-faint">
            Oldest game on the left.{d.clear ? ` Blue: cleared ${d.clear.label.replace("Over ", "")}. Dashed line: the line.` : ""}
          </figcaption>
        </figure>
        <OppBlock title={`Opportunity, average over these ${gs.length} games`} items={d.opportunity.map((o) => ({ label: o.label, value: avgOf(gs, o.key) }))} />
        {gs.length < n ? (
          <p className="text-xs text-mute">
            {played.length < d.published
              ? `Only ${gs.length} game${gs.length === 1 ? "" : "s"} on record before this run.`
              : `This board publishes the last ${d.published} games per player.`}
          </p>
        ) : null}
        {older.length ? <p className="text-xs text-mute">Includes {older.length} game{older.length === 1 ? "" : "s"} from {[...new Set(older.map((g) => d.seasonNames[g.season!] ?? String(g.season)))].join(", ")} (shown lighter).</p> : null}
      </div>
    );
  };

  const seasonView = () => {
    if (!d.season) return <p className="text-sm text-mute">Season averages are not published on this board yet. They appear from the next data refresh.</p>;
    if (!d.season.games) return <p className="text-sm text-mute">No {d.seasonText} regular-season games played yet.</p>;
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Stat label={`${d.stat}, per game`} value={d.season.avg != null ? f1(d.season.avg) : "–"} sub={`${d.seasonText} regular season`} />
          <Stat label="Games played" value={String(d.season.games)} sub="before this run" />
        </div>
        <OppBlock title="Opportunity, season average per game" items={d.opportunity.map((o) => ({ label: o.label, value: d.season!.opportunity[o.key] ?? null }))} />
        {d.season.games < 5 ? <p className="text-xs text-mute">A small sample: {d.season.games} game{d.season.games === 1 ? "" : "s"} this season.</p> : null}
      </div>
    );
  };

  const logView = () => {
    if (!d.games.length) return <p className="text-sm text-mute">No past games on record for this player.</p>;
    return (
      <div>
        <table className="w-full text-xs">
          <thead className="text-faint">
            <tr>
              <th className="py-1 text-left font-500">Date</th>
              <th className="text-left font-500">Opp</th>
              <th className="text-right font-500">{d.stat}</th>
              {d.opportunity.map((o) => <th key={o.key} className="text-right font-500">{o.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {d.games.map((g) => (
              <tr key={g.date} className={`border-t border-navy-700/70 ${other(g) ? "text-faint" : ""}`}>
                <td className="py-1.5 text-mute">{day(g.date)}{other(g) ? <span className="ml-1 text-[0.6rem] text-faint">{d.seasonNames[g.season!] ?? g.season}</span> : null}</td>
                <td className="text-mute">{g.opp}</td>
                <td className={`text-right font-mono ${clears(g.value) ? "text-model" : "text-ink"}`}>{g.value == null ? "–" : f1(g.value)}</td>
                {d.opportunity.map((o) => <td key={o.key} className="text-right font-mono text-mute">{g.opp_[o.key] == null ? "–" : f1(g.opp_[o.key]!)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1.5 text-[0.68rem] text-faint">The last {d.games.length} games he played, newest first. {d.opportunity.length ? "Right-hand columns are opportunity, not results." : ""}</p>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div role="tablist" aria-label="History range" className="flex gap-0.5 rounded-lg bg-navy-850 p-0.5">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`min-h-9 flex-1 rounded-md px-1 text-xs sm:text-sm ${tab === t ? "bg-navy-600 font-500 text-ink" : "text-mute hover:text-ink"}`}>
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={tab}>
        {tab === "Last 5" ? windowView(5) : tab === "Last 10" ? windowView(10) : tab === "Season" ? seasonView() : logView()}
      </div>
      <p className="text-[0.65rem] text-faint">Past games only. Shown for context; the model does not use these figures.</p>
    </div>
  );
}

function avgOf(gs: HistoryTabsData["games"], key: string): number | null {
  const v = gs.map((g) => g.opp_[key]).filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
