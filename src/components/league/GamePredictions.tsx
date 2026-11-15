import Link from "next/link";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell, Unavailable } from "@/components/ui/primitives";
import { formatKickoff, formatPct } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameView, type League } from "@/types/domain";
import { browseHref } from "./href";

const LEAGUE_NAME: Record<League, string> = { nfl: "NFL", nba: "NBA" };
const n1 = (x: number) => x.toFixed(1);
const signed = (x: number) => (x === 0 ? "pick'em" : `${x > 0 ? "+" : "−"}${Math.abs(x) % 1 === 0 ? Math.abs(x).toFixed(0) : Math.abs(x).toFixed(1)}`);

function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });
}

function Stat({ label, children, note }: { label: string; children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 font-display text-2xl font-600 leading-tight text-model">{children}</dd>
      {note ? <p className="mt-0.5 text-xs text-mute">{note}</p> : null}
    </div>
  );
}

/**
 * One matchup: everything the game model publishes for it, in plain words. Blue is the model, white is the
 * sportsbook line, and where no line is published the card says so. Nothing is calculated here.
 */
function GameCard({ g, league }: { g: GameView; league: League }) {
  const fav = g.projectedMargin >= 0 ? g.home : g.away;
  const dog = g.projectedMargin >= 0 ? g.away : g.home;
  const margin = Math.abs(g.projectedMargin);
  const wp = isLocked(g.winProbability) ? null : g.projectedMargin >= 0 ? g.winProbability.home : g.winProbability.away;
  const m = g.market;
  const sp = isLocked(g.atSpread) ? null : g.atSpread;
  const tot = isLocked(g.atTotal) ? null : g.atTotal;
  const started = g.status !== "scheduled";
  // The side of the market spread the model's own distribution gives the better chance.
  const spreadSide = sp ? (sp.home >= sp.away ? { team: g.home, line: sp.line, p: sp.home } : { team: g.away, line: -sp.line, p: sp.away }) : null;
  const totalSide = tot ? (tot.over >= tot.under ? { side: "Over", p: tot.over } : { side: "Under", p: tot.under }) : null;

  return (
    <article id={`g-${g.id}`} className="scroll-mt-24 overflow-hidden rounded-xl bg-navy-900">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-navy-700 px-4 py-3.5 sm:px-5">
        <span className="flex items-center gap-2">
          <TeamBadge league={league} abbr={g.away.abbr} size="sm" />
          <span className="text-faint">@</span>
          <TeamBadge league={league} abbr={g.home.abbr} size="sm" />
        </span>
        <h3 className="min-w-0 flex-1 truncate text-[1.05rem] font-600 text-ink">
          {g.away.name} at {g.home.name}
        </h3>
        <p className="text-xs text-faint">
          {started ? "Started" : formatKickoff(g.startTime)}
          {g.neutral ? " · neutral site" : ""}
        </p>
      </header>

      <div className="grid gap-x-8 gap-y-5 px-4 py-5 sm:grid-cols-[1.25fr_1fr] sm:px-5">
        {/* the model */}
        <section aria-label="Model prediction">
          <p className="text-xs text-faint">Model Room predicts</p>
          <p className="mt-1 font-display text-4xl font-700 leading-none text-ink">
            {margin < 0.05 ? "A toss-up" : `${fav.abbr} to win`}
          </p>
          <p className="mt-1.5 text-sm text-mute">
            {wp != null ? (
              <><span className="font-600 text-model">{formatPct(wp)}</span> chance &middot; {formatPct(1 - wp)} for {dog.abbr}</>
            ) : isLocked(g.winProbability) ? (
              <span className="inline-flex items-center gap-2">Win probability <LockedCell requires={g.winProbability.requires} /></span>
            ) : null}
          </p>
          {wp != null ? (
            <div className="mt-3 h-2 max-w-sm overflow-hidden rounded-full bg-navy-600" aria-hidden="true">
              <div className="h-full bg-model" style={{ width: `${Math.round(wp * 100)}%` }} />
            </div>
          ) : null}

          <dl className="mt-5 grid grid-cols-3 gap-4">
            <Stat label="Projected score" note={!isLocked(g.projectedScore) ? `${g.away.abbr} – ${g.home.abbr}` : undefined}>
              {isLocked(g.projectedScore) ? <LockedCell requires={g.projectedScore.requires} /> : `${n1(g.projectedScore.away)} – ${n1(g.projectedScore.home)}`}
            </Stat>
            <Stat
              label="Projected margin"
              note={!isLocked(g.ranges) && g.ranges.margin ? `8 in 10 games: ${g.home.abbr} ${signed(g.ranges.margin[0])} to ${signed(g.ranges.margin[1])}` : undefined}
            >
              {margin < 0.05 ? "Even" : `${fav.abbr} by ${n1(margin)}`}
            </Stat>
            <Stat label="Projected total" note={!isLocked(g.ranges) && g.ranges.total ? `8 in 10 games: ${n1(g.ranges.total[0])} to ${n1(g.ranges.total[1])}` : undefined}>
              {n1(g.modelTotal)}
            </Stat>
          </dl>
        </section>

        {/* the sportsbook line, and the model's read on it */}
        <section aria-label="Sportsbook line" className="rounded-lg bg-navy-850 p-4">
          <p className="text-xs text-faint">Sportsbook line</p>
          {m && (m.spread != null || m.total != null) ? (
            <>
              <dl className="mt-2 space-y-3">
                <div>
                  <dt className="text-xs text-faint">Spread</dt>
                  {m.spread != null ? (
                    <>
                      <dd className="font-display text-xl font-600 leading-tight text-market">
                        {m.spread <= 0 ? g.home.abbr : g.away.abbr} {signed(-Math.abs(m.spread))}
                      </dd>
                      {spreadSide ? (
                        <p className="text-xs text-mute">
                          Model: <span className="font-600 text-model">{spreadSide.team.abbr} {signed(spreadSide.line)}</span> covers {formatPct(spreadSide.p)} of the time
                        </p>
                      ) : isLocked(g.atSpread) ? (
                        <p className="flex items-center gap-2 text-xs text-mute">Model&apos;s chance at this spread <LockedCell requires={g.atSpread.requires} /></p>
                      ) : null}
                    </>
                  ) : (
                    <dd className="text-sm text-faint">No spread published</dd>
                  )}
                </div>
                <div>
                  <dt className="text-xs text-faint">Total</dt>
                  {m.total != null ? (
                    <>
                      <dd className="font-display text-xl font-600 leading-tight text-market">{m.total}</dd>
                      {totalSide && tot ? (
                        <p className="text-xs text-mute">
                          Model: <span className="font-600 text-model">{totalSide.side} {tot.line}</span> {formatPct(totalSide.p)} &middot; over {formatPct(tot.over)}, under {formatPct(tot.under)}
                        </p>
                      ) : isLocked(g.atTotal) ? (
                        <p className="flex items-center gap-2 text-xs text-mute">Model&apos;s over/under chance <LockedCell requires={g.atTotal.requires} /></p>
                      ) : null}
                    </>
                  ) : (
                    <dd className="text-sm text-faint">No total published</dd>
                  )}
                </div>
              </dl>
              <p className="mt-3 text-[0.7rem] text-faint">
                {m.sources.includes("nflverse") && !m.books ? "Line as published by nflverse" : `Middle line of ${m.books} sportsbooks`}. Not a recommendation.
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-mute">
              No sportsbook line is published for this game yet, so there is no spread or over/under to compare against. The numbers on the left are the model&apos;s own.
            </p>
          )}
        </section>
      </div>

      <details className="group border-t border-navy-700">
        <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm sm:px-5 [&::-webkit-details-marker]:hidden">
          <span className="font-500 text-ink">Team details</span>
          <svg viewBox="0 0 12 12" className="h-3 w-3 text-faint transition-transform group-open:rotate-180" aria-hidden="true"><path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
        </summary>
        <ul className="space-y-1.5 px-4 pb-4 text-sm text-mute sm:px-5">
          <li>
            Rest: {g.away.abbr} {g.rest.awayDays ?? "–"} days{g.rest.awayB2b ? " (second night of a back-to-back)" : ""}, {g.home.abbr} {g.rest.homeDays ?? "–"} days
            {g.rest.homeB2b ? " (second night of a back-to-back)" : ""}.
          </li>
          {g.quarterbacks ? <li>Projected quarterbacks: {g.away.abbr} {g.quarterbacks.away ?? "not known"}, {g.home.abbr} {g.quarterbacks.home ?? "not known"}.</li> : null}
          <li>
            Injuries in the projection:{" "}
            {isLocked(g.injuryAdjustment) ? <LockedCell requires={g.injuryAdjustment.requires} /> : g.injuryAdjustment == null ? "no injury adjustment recorded for this game" : `${signed(g.injuryAdjustment)} points to ${g.home.abbr}'s margin`}
            {!isLocked(g.qbAdjustment) && g.qbAdjustment != null ? `; quarterback adjustment ${signed(g.qbAdjustment)} points` : ""}.
          </li>
          {g.availability ? (
            <li>
              Listed out or doubtful: {g.away.abbr} {g.availability.away.filter((p) => p.status === "out" || p.status === "doubtful").length}, {g.home.abbr}{" "}
              {g.availability.home.filter((p) => p.status === "out" || p.status === "doubtful").length}.
            </li>
          ) : (
            <li>No injury feed for this game.</li>
          )}
          <li>
            <Link href={browseHref(league, { game: g.id })} className="font-500 text-model hover:underline">Player props for this game</Link>
          </li>
        </ul>
      </details>
    </article>
  );
}

export async function GamePredictions({ league }: { league: League }) {
  const viewer = await getViewer();
  const b = await getLeagueBoard(league, viewer.tier);
  if (!b.ok) return <Unavailable title={`${LEAGUE_NAME[league]} predictions are not available`} body={b.reason} />;
  const days = new Map<string, GameView[]>();
  for (const g of b.upcoming) days.set(g.gameDate, [...(days.get(g.gameDate) ?? []), g]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl font-600 leading-none text-ink sm:text-5xl">{LEAGUE_NAME[league]} game predictions</h1>
        <p className="mt-3 max-w-2xl text-[1.02rem] leading-relaxed text-mute">
          Who we expect to win, by how much, and how many points. <span className="text-model">Blue</span> is the model; <span className="text-market">white</span> is the sportsbook line.
        </p>
      </div>
      {b.upcoming.length === 0 ? (
        <p className="text-mute">No upcoming {LEAGUE_NAME[league]} games are on the board right now.</p>
      ) : (
        [...days.entries()].map(([date, games]) => (
          <section key={date} className="space-y-3">
            <h2 className="text-sm text-faint">{dayLabel(date)}</h2>
            {games.map((g) => <GameCard key={g.id} g={g} league={league} />)}
          </section>
        ))
      )}
      <p className="text-xs leading-relaxed text-faint">
        Model {b.model.version}. The game model projects the final score, margin, total and win probability. It does not project quarters, halves,
        team totals as separate bets, or team statistics such as rebounds or turnovers, so none are shown.{" "}
        <Link href={`/${league}?view=games`} className="text-mute underline hover:text-ink">Full board</Link>
      </p>
    </div>
  );
}
