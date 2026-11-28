"use client";

import { useState } from "react";
import { EVIDENCE_SECTIONS, type LegEvidence } from "@/lib/parlay/evidence";
import type { LegOption } from "@/lib/parlay/types";

/**
 * Evidence review across the boards (TEST). Separate from the model's ranking and from Picks to consider: candidates
 * and their evidence counts come from fixed rules; the AI only says which deserve a closer look and why, citing the
 * same stored evidence. Nothing here is a pick.
 */
type Claim = { text: string; cites: string[] };
type Item = { leg: LegOption; gameLabel: string; market: { kind: string; p: number } | null; gap: number | null; supports: number; against: number; quality: number; flags: string[]; list: string };
type Ai = { status: "ok"; model: string; cached: boolean; text: { overview: string; candidates: { id: string; verdict: string; why: Claim; risk: Claim }[] } }
  | { status: "unavailable"; reason: string; message: string };
const pct = (p: number) => `${(p * 100).toFixed(1)}%`;

export function BoardReview({ slipIds, onAdd, ai }: { slipIds: string[]; onAdd: (l: LegOption) => void; ai: { enabled: boolean; model: string } }) {
  const [data, setData] = useState<{ items: Item[]; evidence: Record<string, LegEvidence>; scanned: number; ai?: Ai } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (withAi: boolean) => {
    setBusy(true);
    try {
      const r = await fetch("/api/parlay/review", { method: withAi ? "POST" : "GET" });
      setData(await r.json());
    } catch {
      setData({ items: [], evidence: {}, scanned: 0, ai: { status: "unavailable", reason: "error", message: "Couldn't reach the server." } });
    } finally {
      setBusy(false);
    }
  };
  const notes = new Map(data?.ai?.status === "ok" ? data.ai.text.candidates.map((c) => [c.id, c]) : []);
  const lists = ["closer look", "possible weakness"] as const;
  return (
    <section aria-label="Evidence review" className="rounded-xl border border-navy-700 bg-navy-900">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-navy-700 px-4 py-3">
        <div>
          <h2 className="font-display text-xl font-700 text-ink">Evidence review</h2>
          <p className="text-xs text-mute">Every player and stat on both boards, checked against stored evidence. Not the model&apos;s ranking and not picks.</p>
        </div>
        <div className="flex gap-2">
          {data === null ? (
            <button onClick={() => run(false)} disabled={busy} className="rounded-md border border-navy-600 px-3 py-1.5 text-sm font-600 text-ink hover:border-model disabled:opacity-50">{busy ? "Checking…" : "Check the boards"}</button>
          ) : ai.enabled && data.ai?.status !== "ok" ? (
            <button onClick={() => run(true)} disabled={busy} className="rounded-md border border-navy-600 px-3 py-1.5 text-sm font-600 text-ink hover:border-model disabled:opacity-50">{busy ? "Reviewing…" : "Review with AI"}</button>
          ) : null}
        </div>
      </div>
      {data ? (
        <div className="space-y-3 p-4 text-sm">
          <p className="text-xs text-faint">
            {data.scanned} player-stat lines checked. One vote per kind of evidence (form, role, matchup, injuries, game environment); the model&apos;s own numbers don&apos;t vote.
          </p>
          {data.ai?.status === "unavailable" ? <p className="text-mute">{data.ai.message}</p> : null}
          {data.ai?.status === "ok" && data.ai.text.overview ? <p className="text-ink">{data.ai.text.overview}</p> : null}
          {lists.map((name) => {
            const xs = data.items.map((x, i) => ({ x, i })).filter(({ x }) => x.list === name);
            if (!xs.length) return null;
            return (
              <div key={name}>
                <p className={`font-600 ${name === "closer look" ? "text-good" : "text-edge"}`}>{name === "closer look" ? "Evidence lines up with the model" : "Possible model weakness"}</p>
                <ul className="mt-1 space-y-1.5">
                  {xs.map(({ x, i }) => {
                    const n = notes.get(`C${i + 1}`);
                    const ev = data.evidence[x.leg.id];
                    const added = slipIds.includes(x.leg.id);
                    return (
                      <li key={x.leg.id} className="rounded-md bg-navy-850 px-3 py-2">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-ink">{x.leg.label}</p>
                            <p className="text-[0.75rem] text-faint">
                              {x.gameLabel} · model {pct(x.leg.p)}
                              {x.market ? ` · ${x.market.kind === "polymarket" ? "Polymarket" : "sportsbooks"} ${pct(x.market.p)}` : " · no market price"}
                              {" · "}evidence {x.supports} for, {x.against} against{x.flags.length ? ` · ${x.flags.join(", ")}` : ""}
                            </p>
                          </div>
                          <button onClick={() => onAdd(x.leg)} disabled={added} className="rounded-md border border-navy-600 px-2.5 py-1 text-sm font-600 text-ink hover:border-model disabled:text-faint">{added ? "Added" : "Add"}</button>
                        </div>
                        {n ? (
                          <div className="mt-1 space-y-0.5 text-mute">
                            <p className="text-[0.72rem] text-faint">AI: {n.verdict}</p>
                            {n.why.text ? <p><span className="font-600 text-good">Why: </span>{n.why.text}</p> : null}
                            {n.risk.text ? <p><span className="font-600 text-edge">Risk: </span>{n.risk.text}</p> : null}
                          </div>
                        ) : null}
                        {ev?.items.length ? (
                          <details className="mt-1 text-[0.78rem]">
                            <summary className="cursor-pointer text-mute hover:text-ink">Evidence</summary>
                            <div className="mt-1 space-y-1.5">
                              {EVIDENCE_SECTIONS.map((sec) => {
                                const it = ev.items.filter((e) => sec.kinds.includes(e.kind));
                                return it.length ? (
                                  <div key={sec.title}>
                                    <p className="font-600 text-ink">{sec.title}</p>
                                    <ul>{it.map((e) => <li key={e.id} className="text-mute"><span className={e.lean === "supports" ? "text-good" : e.lean === "against" ? "text-edge" : "text-faint"}>{e.lean === "supports" ? "+ " : e.lean === "against" ? "− " : "· "}</span>{e.text} <span className="text-[0.7rem] text-faint">{e.source}</span></li>)}</ul>
                                  </div>
                                ) : null;
                              })}
                              {ev.missing.length ? <p className="text-faint">Not available: {ev.missing.join(" ")}</p> : null}
                            </div>
                          </details>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
          {!data.items.length ? <p className="text-mute">Nothing to review right now.</p> : null}
        </div>
      ) : null}
    </section>
  );
}
