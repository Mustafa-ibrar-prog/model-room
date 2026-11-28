"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { propSelection, type Selection } from "@/lib/parlay/cardMath";
import type { LegOption, PropCard } from "@/lib/parlay/types";

/** Shared by the Parlay Builder and the props explorer (TEST): one card per player per stat, with a side and threshold
 *  picker. The numbers shown are computed from the card's stored model distribution and exact market quotes; adding a
 *  selection asks the server for the leg, which derives it again on its own. */
type League = "nba" | "nfl";
export const SLIP_STORE = "mr_parlay_slip_v1";
const pct = (p: number | null | undefined, d = 1) => (p == null ? "–" : `${(p * 100).toFixed(d)}%`);
const odds = (a: number | null | undefined) => (a == null ? "–" : a > 0 ? `+${a}` : `${a}`);
const time = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/Los_Angeles", weekday: "short", hour: "numeric", minute: "2-digit" }) + " PT" : "";

/** The threshold a card opens on: the books' line, else a Polymarket line, else the model's coin flip. */
export function startK(c: PropCard): number {
  const has = (k: number) => c.thresholds.includes(k);
  if (c.bookLine !== null && has(c.bookLine + 0.5)) return c.bookLine + 0.5;
  const pmk = c.pm.map((x) => x.line).filter(has).sort((a, b) => Math.abs(a - c.projection) - Math.abs(b - c.projection))[0];
  if (pmk !== undefined) return pmk;
  let best = c.thresholds[0];
  for (const k of c.thresholds) {
    const p = c.grid.p[Math.round((k - c.grid.k0) / c.grid.step)];
    const pb = c.grid.p[Math.round((best - c.grid.k0) / c.grid.step)];
    if (Math.abs(p - 0.5) < Math.abs(pb - 0.5)) best = k;
  }
  return best;
}

export function useAdd(league: League, onAdd: (l: LegOption) => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = useCallback(async (id: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`/api/parlay/legs?league=${league}&id=${encodeURIComponent(id)}`);
      const d = await r.json();
      if (!r.ok || !d.leg) throw new Error(d.error ?? "That selection isn't available.");
      onAdd(d.leg as LegOption);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't add this.");
    } finally {
      setBusy(false);
    }
  }, [league, onAdd]);
  return { busy, err, go };
}

export function SideToggle({ value, onChange, labels, name }: { value: 1 | -1; onChange: (v: 1 | -1) => void; labels: [string, string]; name: string }) {
  return (
    <div className="inline-flex rounded-md border border-navy-600 p-0.5" role="radiogroup" aria-label={name}>
      {([1, -1] as const).map((v, i) => (
        <button key={v} role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={`rounded px-2 py-0.5 text-xs font-600 ${value === v ? "bg-navy-700 text-ink" : "text-mute hover:text-ink"}`}>{labels[i]}</button>
      ))}
    </div>
  );
}

export function Market({ s, pmOn }: { s: Selection; pmOn: boolean }) {
  const c = (x: number | null) => (x === null ? "–" : `${Math.round(x * 100)}¢`);
  return (
    <div className="grid gap-x-4 gap-y-1 text-[0.75rem] sm:grid-cols-2">
      <p>
        <span className="text-faint">Sportsbook </span>
        {s.book ? (
          <>
            <span className="font-mono text-market">{odds(s.book.american)}</span>{" "}
            <span className="text-mute">{s.book.title}{s.book.books > 1 ? ` (best of ${s.book.books})` : ""}</span>
          </>
        ) : (
          <span className="text-mute">No sportsbook price available{s.otherBookLines.length ? ` at this line (books: ${s.otherBookLines.join(", ")})` : ""}</span>
        )}
      </p>
      {pmOn ? (
        <p>
          <span className="text-faint">Polymarket </span>
          {s.pm ? (
            s.pm.implied !== null ? (
              <><span className="font-mono text-market">{pct(s.pm.implied)}</span> <span className="text-mute">bid {c(s.pm.bid)} / ask {c(s.pm.ask)}</span></>
            ) : (
              <span className="text-mute">no two-sided price (bid {c(s.pm.bid)}, ask {c(s.pm.ask)})</span>
            )
          ) : (
            <span className="text-mute">No Polymarket contract at this line{s.otherPmLines.length ? ` (Polymarket lists ${s.otherPmLines.map((x) => `${x}+`).join(", ")})` : ""}</span>
          )}
        </p>
      ) : null}
    </div>
  );
}

export function Gap({ s }: { s: Selection }) {
  if (!s.gap) return <span className="text-faint">–</span>;
  const d = s.gap.d * 100;
  return (
    <span title={`Model minus ${s.gap.vs} implied probability`} className={`font-mono ${d > 0 ? "text-good" : d < 0 ? "text-edge" : "text-ink"}`}>
      {d > 0 ? "+" : ""}{d.toFixed(1)}
    </span>
  );
}

/** One player, one stat: pick Over / Under and a threshold; every number follows the selection. */
export function PropRow({ c, league, inSlip, onAdd, head, as = "li", addText = "Add" }: { c: PropCard; league: League; inSlip: Set<string>; onAdd: (l: LegOption) => void;
  head?: ReactNode; as?: "li" | "div"; addText?: string }) {
  const [side, setSide] = useState<1 | -1>(1);
  const [K, setK] = useState<number>(() => startK(c));
  const [open, setOpen] = useState(false);
  const s = useMemo(() => propSelection(c, K, side), [c, K, side]);
  const id = s.id;
  const added = s.ids.some((x) => inSlip.has(x));
  const { busy, err, go } = useAdd(league, onAdd);
  const bookKs = new Set(c.quotes.map((q) => q.line + 0.5));
  const pmKs = new Set(c.pm.map((x) => x.line));
  const Tag = as;
  return (
    <Tag className="px-3 py-2.5" data-card={c.key}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {head ?? (
          <div className="min-w-[9rem] flex-1">
            <p className="truncate text-sm font-600 text-ink">{c.playerName}</p>
            <p className="text-xs text-faint">
              {c.team}{c.opp ? ` vs ${c.opp}` : ""} · projection <span className="font-mono text-model">{Math.round(c.projection)}</span>
              {c.injury && !/^available$/i.test(c.injury) ? <span className="text-pending"> · {c.injury}</span> : null}
            </p>
          </div>
        )}
        <SideToggle value={side} onChange={setSide} labels={["Over", "Under"]} name={`${c.playerName} ${c.noun} side`} />
        <select value={K} onChange={(e) => setK(Number(e.target.value))} aria-label={`${c.playerName} ${c.noun} threshold`}
          className="rounded-md border border-navy-600 bg-navy-950 px-2 py-1 font-mono text-xs text-ink">
          {c.thresholds.map((k) => (
            <option key={k} value={k}>
              {side > 0 ? `${k}+` : `under ${k}`}{bookKs.has(k) ? ` · book ${k - 0.5}` : ""}{pmKs.has(k) ? " · Polymarket" : ""}
            </option>
          ))}
        </select>
        <div className="w-14 text-right">
          <p className="font-mono text-sm text-model">{pct(s.p)}</p>
          <p className="text-[0.68rem] text-faint">model</p>
        </div>
        <div className="w-12 text-right">
          <p className="text-sm"><Gap s={s} /></p>
          <p className="text-[0.68rem] text-faint">gap</p>
        </div>
        <button onClick={() => go(id)} disabled={added || busy || s.p === null} aria-label={`Add ${s.label}`}
          className="rounded-md border border-navy-600 px-2.5 py-1 text-sm font-600 text-ink hover:border-model disabled:border-navy-700 disabled:text-faint">
          {added ? "Added" : busy ? "…" : addText}
        </button>
      </div>
      <div className="mt-1.5 space-y-1">
        <Market s={s} pmOn={c.pmFetchedAt !== null} />
        <p className="text-[0.75rem]">
          {s.last10 ? (
            <>
              <span className="text-faint">Last 5 </span><span className="font-mono text-ink">{s.last10.last5Hits}/{s.last10.last5Games}</span>
              <span className="text-faint"> · last 10 </span><Record10 r={s.last10} />
            </>
          ) : <span className="text-faint">No game log for this stat</span>}
        </p>
        {c.quotes.length ? (
          <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="text-[0.72rem] text-mute hover:text-ink">
            {open ? "Hide" : "Show"} {c.quotes.length} sportsbook{c.quotes.length > 1 ? "s" : ""}
          </button>
        ) : null}
        {open ? <PropQuotes c={c} line={K - 0.5} /> : null}
        {err ? <p className="text-[0.72rem] text-edge">{err}</p> : null}
      </div>
    </Tag>
  );
}

function PropQuotes({ c, line }: { c: PropCard; line: number }) {
  const qs = [...c.quotes].sort((a, b) => a.title.localeCompare(b.title));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[18rem] text-left text-[0.75rem]">
        <thead><tr className="text-faint"><th className="py-0.5 font-500">Sportsbook</th><th className="font-500">Line</th><th className="font-500">Over</th><th className="font-500">Under</th><th className="font-500">Updated</th></tr></thead>
        <tbody>
          {qs.map((q) => (
            <tr key={q.book} className="border-t border-navy-700">
              <td className="py-1 text-ink">{q.title}</td>
              <td className={`font-mono ${Math.abs(q.line - line) < 1e-9 ? "text-ink" : "text-pending"}`}>{q.line}</td>
              <td className="font-mono text-market">{q.over === null ? "no price" : odds(q.over)}</td>
              <td className="font-mono text-market">{q.under === null ? "no price" : odds(q.under)}</td>
              <td className="text-faint">{q.lastUpdate ? time(q.lastUpdate) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[0.7rem] text-faint">Lines in yellow are a different threshold from the one selected.</p>
    </div>
  );
}

export function Record10({ r }: { r: NonNullable<LegOption["last10"]> }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={r.text}>
      <span className="flex gap-px" aria-hidden="true">
        {[...r.marks].reverse().map((m, i) => (
          <span key={i} className={`h-2.5 w-1 rounded-sm ${m > 0 ? "bg-good" : m === 0 ? "bg-pending" : "bg-navy-600"}`} />
        ))}
      </span>
      <span className="font-mono text-ink">{r.hits}/{r.games}</span>
      <span className="text-faint">avg {r.avg}{r.pushes ? `, ${r.pushes} push` : ""}</span>
    </span>
  );
}


/** Explorer: one player entry for the selected stat, with the picker; "Add to parlay" saves to the same browser slip the
 *  Parlay Builder reads (per-browser convenience; legs are re-priced on the server when the builder opens). */
export function ExplorerPick({ c, league, head }: { c: PropCard; league: League; head: ReactNode }) {
  const [ids, setIds] = useState<Set<string>>(new Set());
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setIds(new Set(readSlip().map((l) => l.id))), 0);
    return () => clearTimeout(t);
  }, []);
  const add = useCallback((l: LegOption) => {
    const slip = readSlip();
    if (slip.some((x) => x.id === l.id)) return;
    if (slip.length >= 10) { setNote("Your parlay already has 10 legs."); return; }
    try {
      localStorage.setItem(SLIP_STORE, JSON.stringify([...slip, l]));
      setIds(new Set([...slip, l].map((x) => x.id)));
      setNote(`Added to your parlay (${slip.length + 1} leg${slip.length ? "s" : ""}).`);
    } catch {
      setNote("This browser blocked saving, so the leg couldn't be added.");
    }
  }, []);
  return (
    <article className="rounded-xl bg-navy-900">
      <PropRow c={c} league={league} inSlip={ids} onAdd={add} head={head} as="div" addText="Add to parlay" />
      {note ? <p className="px-3 pb-2.5 text-[0.75rem] text-mute">{note} <a href="/parlay" className="font-600 text-model hover:underline">Open parlay</a></p> : null}
    </article>
  );
}

function readSlip(): LegOption[] {
  try {
    const raw = localStorage.getItem(SLIP_STORE);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? (v as LegOption[]) : [];
  } catch {
    return [];
  }
}
