import type { ReactNode } from "react";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { formatKickoff } from "@/lib/format";
import type { League } from "@/types/domain";
import type { HistoryGame, PickRecord, PickResult, PickRow } from "@/types/history";
import {
  gameStatus, marginText, modelText, num, outcomeText, pickText, provenanceOf, rateText, RESULT_LABEL, scoreDiff, tally, winProbs,
  type GameCtx, type GameStatus, type Provenance,
} from "./picks";

/**
 * The cards on Performance. Everything shown is read from the stored pick and the stored result:
 * nothing here chooses a side, moves a line or decides a grade.
 */

const TONE: Record<PickResult, string> = {
  hit: "bg-good text-navy-950",
  miss: "bg-danger text-navy-950",
  push: "border border-navy-600 bg-navy-800 text-ink",
  void: "border border-dashed border-navy-600 text-mute",
  cancelled: "border border-dashed border-navy-600 text-mute",
  pending: "bg-navy-800 text-faint",
};

export function Badge({ result, small = false }: { result: PickResult; small?: boolean }) {
  return (
    <span className={`inline-flex items-center justify-center rounded-md font-700 leading-none tracking-wide ${small ? "h-6 min-w-[3.4rem] px-1.5 text-[0.68rem]" : "h-7 min-w-[4.5rem] px-2 text-xs"} ${TONE[result]}`}>
      {RESULT_LABEL[result]}
    </span>
  );
}

/** Where a grade would be, when there is nothing to grade. */
function NoGrade({ small = false }: { small?: boolean }) {
  return <span className={`inline-flex items-center justify-center text-faint ${small ? "h-6 min-w-[3.4rem] text-[0.68rem]" : "h-7 min-w-[4.5rem] text-xs"}`}>No pick</span>;
}

function Chevron() {
  return (
    <svg viewBox="0 0 12 12" className="h-3.5 w-3.5 shrink-0 text-faint transition-transform group-open:rotate-180" aria-hidden="true">
      <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

const when = (iso: string) =>
  `${new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles" })} PT`;

const PROV_TEXT: Record<Provenance, string> = { pre_game: "Recorded pre-game", reconstructed: "Reconstructed" };

/** The provenance mark: a filled dot for a pick written before the game, a ring for one written afterwards. */
export function ProvDot({ kind }: { kind: Provenance }) {
  return <span aria-hidden="true" className={`inline-block h-2 w-2 shrink-0 rounded-full ${kind === "pre_game" ? "bg-model" : "border border-pending"}`} />;
}

function Prov({ p }: { p: PickRow }) {
  const kind = provenanceOf(p);
  return (
    <span className="mt-1 flex items-center gap-1.5 text-[0.7rem] leading-snug text-faint">
      <ProvDot kind={kind} />
      <span>
        <span className={kind === "pre_game" ? "text-mute" : "text-pending"}>{PROV_TEXT[kind]}</span>
        {kind === "pre_game" ? ` ${when(p.recorded_at)}` : ` from the projection of ${when(p.recorded_at)}`}
      </span>
    </span>
  );
}

const DOT: Record<PickResult, string> = { hit: "bg-good", miss: "bg-danger", push: "bg-navy-600", void: "border border-navy-600", cancelled: "border border-navy-600", pending: "bg-navy-700" };

const STATUS_TONE: Record<GameStatus, string> = {
  Final: "text-mute",
  Live: "text-good",
  Upcoming: "text-model",
  "Not played": "text-faint",
  "Awaiting final": "text-pending",
};

/** The scoreboard: one line per team, the winner in full ink. */
function Scoreboard({ league, g, status }: { league: League; g: HistoryGame; status: GameStatus }) {
  const f = g.final;
  const line = (abbr: string, score: number | null, won: boolean, lost: boolean) => (
    <div className="flex items-center gap-2.5">
      <TeamBadge league={league} abbr={abbr} size="sm" />
      <span className={`w-14 font-display text-xl font-600 leading-none ${lost ? "text-mute" : "text-ink"}`}>{abbr}</span>
      <span className={`ml-auto min-w-9 text-right font-display text-[1.7rem] font-700 leading-none tabular-nums ${won ? "text-ink" : lost ? "text-mute" : "text-faint"}`}>
        {score ?? "–"}
      </span>
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${won ? "bg-ink" : "bg-transparent"}`} />
    </div>
  );
  return (
    <div className="min-w-0">
      <div className="space-y-1.5">
        {line(g.away, f ? f.away : null, !!f && f.away > f.home, !!f && f.away < f.home)}
        {line(g.home, f ? f.home : null, !!f && f.home > f.away, !!f && f.home < f.away)}
      </div>
      <p className="mt-2 text-[0.72rem] leading-none text-faint">
        <span className={`font-600 ${STATUS_TONE[status]}`}>{status}</span>
        {g.start_time ? ` · ${formatKickoff(g.start_time)}` : ""}
      </p>
    </div>
  );
}

const SUMMARY = "grid cursor-pointer list-none items-center gap-x-5 gap-y-3 px-4 py-3.5 sm:px-5 [&::-webkit-details-marker]:hidden hover:bg-navy-850 group-open:border-b group-open:border-navy-700";

function Chip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="flex flex-col items-center gap-1">
      <span className="text-[0.68rem] leading-none text-faint">{label}</span>
      {children}
    </span>
  );
}

/** One row of the expanded table. On phones it stacks: what, the pick, what happened, with the grade at the right. */
function Row({ what, pick, actual, grade, sub }: { what: string; pick: ReactNode; actual: ReactNode; grade: ReactNode; sub?: ReactNode }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-0.5 border-b border-navy-800 px-4 py-3 last:border-b-0 sm:grid-cols-[8.5rem_1.25fr_1fr_4.5rem] sm:px-5">
      <span className="col-span-2 text-[0.72rem] text-faint sm:col-span-1 sm:text-sm sm:text-mute">{what}</span>
      <span className="min-w-0">
        <span className="block text-[1.02rem] font-600 leading-snug text-ink">{pick}</span>
        {sub}
      </span>
      <span className="row-start-3 text-sm text-mute sm:row-start-auto">{actual}</span>
      <span className="row-span-2 row-start-2 flex justify-end self-center sm:row-span-1 sm:row-start-auto">{grade}</span>
    </li>
  );
}

function HeadRow({ cols }: { cols: [string, string, string, string] }) {
  return (
    <li aria-hidden="true" className="hidden grid-cols-[8.5rem_1.25fr_1fr_4.5rem] gap-x-4 px-5 pb-1 pt-3 text-[0.7rem] text-faint sm:grid">
      <span>{cols[0]}</span><span>{cols[1]}</span><span>{cols[2]}</span><span className="text-right">{cols[3]}</span>
    </li>
  );
}

/** A projection's error: a plain number in a neutral box. Deliberately not a green or red grade. */
function Diff({ children }: { children: ReactNode }) {
  return <span className="inline-flex h-7 min-w-[4.5rem] items-center justify-center whitespace-nowrap rounded-md bg-navy-800 px-2 font-mono text-xs text-ink">{children}</span>;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** A game: its stored winner, spread and total picks with their grades, then the projected score beside the real one. */
export function GameCard({ league, g, picks, now }: { league: League; g: HistoryGame; picks: PickRow[]; now: number }) {
  const ctx: GameCtx = { home: g.home, away: g.away, final: g.final };
  const status = gameStatus(g, now);
  const of = (m: PickRow["market"]) => picks.find((p) => p.market === m) ?? null;
  const [winner, spread, total] = [of("moneyline"), of("spread"), of("total")];
  const pre = g.pregame;
  const f = g.final;
  const margin = f ? f.home - f.away : null;
  const probs = winner ? winProbs(winner) : pre ? { home: pre.home_win_prob, away: 1 - pre.home_win_prob } : null;
  const wonBy = margin == null ? "" : margin === 0 ? "Tied" : `${margin > 0 ? g.home : g.away} won by ${Math.abs(margin)}`;
  const waiting = status === "Not played" ? "Game not played" : "Awaiting final score";

  return (
    <details className="group overflow-hidden rounded-xl bg-navy-900">
      <summary className={`${SUMMARY} grid-cols-[1fr_auto] sm:grid-cols-[13.5rem_1fr_auto]`}>
        <Scoreboard league={league} g={g} status={status} />
        <span className="col-span-2 row-start-2 flex justify-between gap-2 sm:col-span-1 sm:row-start-auto sm:justify-end sm:gap-5">
          <Chip label="Winner">{winner ? <Badge result={winner.result} /> : <NoGrade />}</Chip>
          <Chip label="Spread">{spread ? <Badge result={spread.result} /> : <NoGrade />}</Chip>
          <Chip label="Total">{total ? <Badge result={total.result} /> : <NoGrade />}</Chip>
        </span>
        <span className="flex items-center gap-1.5 self-start text-xs text-faint sm:self-center">
          <span className="group-open:hidden">Details</span><span className="hidden group-open:inline">Close</span>
          <Chevron />
        </span>
      </summary>

      <ul>
        <HeadRow cols={["Prediction", "Model pick", "Actual result", "Grade"]} />
        <Row
          what="Winner"
          pick={winner ? pickText(winner) : "No recorded pick"}
          sub={winner ? (
            <>
              {probs ? <span className="block text-xs text-model">Win probability: {g.away} {pct(probs.away)}, {g.home} {pct(probs.home)}</span> : null}
              <Prov p={winner} />
            </>
          ) : <span className="block text-xs text-faint">No winner was recorded before this game.</span>}
          actual={margin == null ? waiting : wonBy}
          grade={winner ? <Badge result={winner.result} /> : <NoGrade />}
        />
        <Row
          what="Spread"
          pick={spread ? pickText(spread) : <span className="font-500 text-mute">No recorded pick</span>}
          sub={spread ? (
            <>
              <span className="block text-xs text-model">
                Model {modelText(spread)}
                {spread.line_books ? <span className="text-faint"> &middot; line from {spread.line_books} sportsbooks</span> : null}
              </span>
              <Prov p={spread} />
            </>
          ) : <span className="block text-xs text-faint">No side and line were stored before this game, so nothing is graded.</span>}
          actual={margin == null ? waiting : spread ? outcomeText(spread, ctx) : wonBy}
          grade={spread ? <Badge result={spread.result} /> : <NoGrade />}
        />
        <Row
          what="Game total"
          pick={total ? pickText(total) : <span className="font-500 text-mute">No recorded pick</span>}
          sub={total ? (
            <>
              <span className="block text-xs text-model">
                Model {modelText(total)}
                {total.line_books ? <span className="text-faint"> &middot; line from {total.line_books} sportsbooks</span> : null}
              </span>
              <Prov p={total} />
            </>
          ) : <span className="block text-xs text-faint">No Over or Under and line were stored before this game, so nothing is graded.</span>}
          actual={f ? `${f.home + f.away} total points` : waiting}
          grade={total ? <Badge result={total.result} /> : <NoGrade />}
        />
      </ul>

      {/* A projected score is a projection, not a bet: it is shown with its error and never as a hit or a miss. */}
      <div className="border-t border-navy-700 bg-navy-950/40">
        <p className="px-4 pt-3 text-sm font-600 text-ink sm:px-5">
          Projected score
          <span className="ml-2 text-xs font-400 text-faint">How close the projection was. Not a pick, so no HIT or MISS.</span>
        </p>
        {pre ? (
          <ul>
            <HeadRow cols={["", "Model projection", "Final", "Difference"]} />
            {([[g.away, pre.pred_away_score, f?.away], [g.home, pre.pred_home_score, f?.home]] as const).map(([abbr, proj, act]) => (
              <Row
                key={abbr}
                what={`${abbr} team score`}
                pick={<span className="font-mono text-[0.98rem] font-500">{num(Math.round(proj * 10) / 10)} projected</span>}
                actual={act == null ? waiting : <span className="font-mono text-ink">{act} actual</span>}
                grade={<Diff>{act == null ? "–" : scoreDiff(proj, act)}</Diff>}
              />
            ))}
            <Row
              what="Margin"
              pick={<span className="font-mono text-[0.98rem] font-500">{marginText(g, pre.pred_margin)}</span>}
              actual={margin == null ? waiting : <span className="font-mono text-ink">{marginText(g, margin)}</span>}
              grade={<Diff>{g.result ? `off ${num(Math.abs(g.result.margin_error))}` : "–"}</Diff>}
            />
            <Row
              what="Total points"
              pick={<span className="font-mono text-[0.98rem] font-500">{num(Math.round(pre.pred_total * 10) / 10)} projected</span>}
              actual={f ? <span className="font-mono text-ink">{f.home + f.away} actual</span> : waiting}
              grade={<Diff>{f ? scoreDiff(pre.pred_total, f.home + f.away) : "–"}</Diff>}
            />
          </ul>
        ) : (
          <p className="px-4 py-3 text-sm text-faint sm:px-5">No projected score was recorded before this game.</p>
        )}
        <p className="px-4 pb-3.5 pt-1 text-xs text-faint sm:px-5">
          Team totals: the model records a projected score for each team, not an Over or Under on it, so there is no team-total pick to grade.
        </p>
      </div>
    </details>
  );
}

function Count({ n, label, tone }: { n: number; label: string; tone: string }) {
  if (!n) return null;
  return <span className={`inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-700 leading-none ${tone}`}>{n}<span className="font-600">{label}</span></span>;
}

/** A game's player picks: the projection, the side and threshold that were stored, the final stat, and the grade. */
export function PropsCard({ league, g, picks, now }: { league: League; g: HistoryGame; picks: PickRow[]; now: number }) {
  const ctx: GameCtx = { home: g.home, away: g.away, final: g.final };
  const status = gameStatus(g, now);
  const rec = tally(picks.map((p) => p.result));
  const byPlayer = new Map<string, PickRow[]>();
  for (const p of picks) byPlayer.set(p.player_id ?? "", [...(byPlayer.get(p.player_id ?? "") ?? []), p]);
  const players = [...byPlayer.values()].sort((a, b) => (a[0].team ?? "").localeCompare(b[0].team ?? "") || (a[0].player ?? "").localeCompare(b[0].player ?? ""));
  const pre = picks.filter((p) => provenanceOf(p) === "pre_game").length;
  const COLS = "sm:grid-cols-[9rem_6.5rem_1.2fr_1fr_3.6rem]";

  return (
    <details className="group overflow-hidden rounded-xl bg-navy-900">
      <summary className={`${SUMMARY} grid-cols-[1fr_auto] sm:grid-cols-[13.5rem_1fr_auto]`}>
        <Scoreboard league={league} g={g} status={status} />
        <span className="col-span-2 row-start-2 flex flex-wrap items-center gap-x-4 gap-y-2 sm:col-span-1 sm:row-start-auto sm:justify-end">
          <span className="text-sm text-mute">
            {rec.hit_rate != null ? <><span className="font-display text-2xl font-700 leading-none text-ink">{rateText(rec)}</span> hit rate</> : rec.pending ? "Not settled yet" : "Nothing to grade"}
          </span>
          <span className="flex flex-wrap gap-1.5">
            <Count n={rec.hit} label="HIT" tone={TONE.hit} />
            <Count n={rec.miss} label="MISS" tone={TONE.miss} />
            <Count n={rec.push} label="PUSH" tone={TONE.push} />
            <Count n={rec.void + rec.cancelled} label="VOID" tone={TONE.void} />
            <Count n={rec.pending} label="PENDING" tone={TONE.pending} />
          </span>
        </span>
        <span className="flex items-center gap-1.5 self-start text-xs text-faint sm:self-center">
          <span className="group-open:hidden">{byPlayer.size} players</span><span className="hidden group-open:inline">Close</span>
          <Chevron />
        </span>
      </summary>

      <div className="px-4 pb-4 sm:px-5">
        <p className="flex items-center gap-1.5 py-3 text-xs text-faint">
          <ProvDot kind={pre === picks.length ? "pre_game" : "reconstructed"} />
          {pre === picks.length
            ? `All ${picks.length} picks were recorded before the game started.`
            : pre === 0
              ? `Reconstructed: these ${picks.length} picks were written after the game started, from the projections recorded before it.`
              : `${pre} recorded before the game started, ${picks.length - pre} reconstructed afterwards from the projections recorded before it.`}
        </p>
        {players.map((rows) => {
          const r = tally(rows.map((p) => p.result));
          return (
            <details key={rows[0].player_id} className="group/p border-t border-navy-700">
              <summary className="flex min-h-12 cursor-pointer list-none items-center gap-x-3 py-2 [&::-webkit-details-marker]:hidden">
                <span className="min-w-0 flex-1 truncate text-[0.98rem] font-600 text-ink">
                  {rows[0].player} <span className="text-xs font-500 text-faint">{rows[0].team}</span>
                </span>
                <span aria-hidden="true" className="hidden gap-0.5 sm:flex">
                  {rows.map((p) => <span key={p.id} className={`h-2.5 w-2.5 rounded-sm ${DOT[p.result]}`} />)}
                </span>
                <span className="w-24 shrink-0 text-right text-xs font-500 text-mute">
                  {r.hit + r.miss ? `${r.hit} of ${r.hit + r.miss} hit` : rows.every((p) => p.result === "void") ? "Did not play" : r.pending ? "Pending" : "\u2013"}
                </span>
                <svg viewBox="0 0 12 12" className="h-3 w-3 shrink-0 text-faint transition-transform group-open/p:rotate-180" aria-hidden="true"><path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
              </summary>
              <div aria-hidden="true" className={`hidden gap-x-4 pb-1 text-[0.7rem] text-faint sm:grid ${COLS}`}>
                <span>Stat</span><span>Projected</span><span>Model pick</span><span>Actual</span><span className="text-right">Grade</span>
              </div>
              <ul className="pb-2.5">
                {rows.map((p) => (
                  <li key={p.id} className={`grid grid-cols-[1fr_auto] items-center gap-x-4 py-1.5 ${COLS}`}>
                    <span className="col-span-2 text-[0.72rem] text-faint sm:col-span-1 sm:text-sm sm:text-mute">{p.stat_label ?? p.stat}</span>
                    <span className="hidden font-mono text-sm text-model sm:block">{p.model_number == null ? "\u2013" : num(Math.round(p.model_number * 10) / 10)}</span>
                    <span className="text-sm text-ink">
                      <span className="font-600">{pickText(p)}</span>
                      {p.model_prob != null ? <span className="text-xs text-faint"> &middot; {pct(p.model_prob)} chance</span> : null}
                      {pre > 0 && pre < picks.length ? <span className="ml-1.5 inline-flex align-middle"><ProvDot kind={provenanceOf(p)} /></span> : null}
                    </span>
                    <span className="row-start-3 text-sm text-mute sm:row-start-auto">
                      <span className="sm:hidden">{p.model_number == null ? "" : `Projected ${num(Math.round(p.model_number * 10) / 10)} \u00b7 `}</span>
                      {outcomeText(p, ctx)}
                    </span>
                    <span className="row-span-2 row-start-2 flex justify-end self-center sm:row-span-1 sm:row-start-auto"><Badge result={p.result} small /></span>
                  </li>
                ))}
              </ul>
            </details>
          );
        })}
      </div>
    </details>
  );
}

/** One record, in full: the hit rate from hits and misses only, and every count that makes it up. */
export function RecordPanel({ label, r, prov, empty }: { label: string; r: PickRecord; prov?: { pre_game: number; reconstructed: number }; empty: string }) {
  const stat = (k: string, v: number, tone = "text-ink") => (
    <div>
      <dt className="text-[0.68rem] leading-none text-faint">{k}</dt>
      <dd className={`mt-1 font-display text-xl font-600 leading-none tabular-nums ${v ? tone : "text-faint"}`}>{v}</dd>
    </div>
  );
  const any = r.graded + r.pending + r.void + r.cancelled > 0;
  return (
    <section aria-label={label} className="flex flex-col rounded-xl bg-navy-900 px-4 py-3.5 sm:p-5">
      <h2 className="text-sm font-600 text-mute">{label}</h2>
      {r.hit_rate != null ? (
        <p className="mt-1 flex items-baseline gap-2">
          <span className="font-display text-4xl font-700 leading-none text-ink sm:text-5xl">{rateText(r)}</span>
          <span className="text-sm text-mute">hit rate</span>
        </p>
      ) : (
        <p className="mt-1 font-display text-2xl font-600 leading-tight text-faint">{any ? "Nothing settled yet" : empty}</p>
      )}
      <dl className="mt-3 grid grid-cols-6 gap-x-2 sm:mt-4">
        {stat("Settled", r.graded)}
        {stat("Hits", r.hit, "text-good")}
        {stat("Misses", r.miss, "text-danger")}
        {stat("Pushes", r.push)}
        {stat("Voids", r.void + r.cancelled)}
        {stat("Pending", r.pending)}
      </dl>
      {prov && prov.pre_game + prov.reconstructed > 0 ? (
        <p className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-3 text-xs text-faint">
          <span className="flex items-center gap-1.5"><ProvDot kind="pre_game" />{prov.pre_game.toLocaleString("en-US")} recorded pre-game</span>
          <span className="flex items-center gap-1.5"><ProvDot kind="reconstructed" />{prov.reconstructed.toLocaleString("en-US")} reconstructed</span>
        </p>
      ) : null}
    </section>
  );
}
