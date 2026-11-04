import Link from "next/link";
import { favoredLine, formatKickoff, formatNumber, formatPct } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { loadPropsBoard } from "@/server/engine/board";
import { getViewer } from "@/server/viewer";
import { liveGameLines, ownerLiveMarkets, type LiveGameLines } from "@/server/markets/polymarketLive";
import { isLocked, type GameView, type League } from "@/types/domain";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { Gated, Unavailable } from "@/components/ui/primitives";
import { InjuryLine } from "@/components/injuries/InjuryFlags";

function dayKey(g: GameView): string {
  const [y, m, d] = g.gameDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" });
}

type Avail = { players: number; lines: number; priced: number };

function Row({ g, league, now, avail, live }: { g: GameView; league: League; now: number; avail: Avail | undefined; live?: LiveGameLines }) {
  const model = favoredLine(g.modelSpread, g.home.abbr, g.away.abbr);
  // Owner view on the test site: Polymarket US's main line (live) stands in for the market line.
  const mSpread = live?.spread ? live.spread.home : g.market?.spread ?? null;
  const mTotal = live?.total ? live.total.line : g.market?.total ?? null;
  const pm = live?.spread || live?.total ? "PM " : "";
  const market = mSpread != null ? favoredLine(mSpread, g.home.abbr, g.away.abbr) : null;
  const started = g.startTime ? Date.parse(g.startTime) <= now : false;
  const se = isLocked(g.spreadEdge) ? null : live?.spread && g.modelSpread != null ? live.spread.home - g.modelSpread : g.spreadEdge;
  const te = isLocked(g.totalEdge) ? null : live?.total && g.modelTotal != null ? g.modelTotal - live.total.line : g.totalEdge;
  const cell = "rounded-md bg-navy-850 px-2 py-1.5 text-center";
  const when = started ? "Started" : formatKickoff(g.startTime).split(", ").slice(-1)[0];
  const props = (
    <Link
      href={`/props?sport=${league}&game=${encodeURIComponent(g.id)}`}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-navy-800 px-3 py-1 text-sm font-600 text-ink hover:bg-navy-700"
    >
      Props{avail?.players ? <span className="font-400 text-mute">{avail.players}</span> : null}
      <span aria-hidden="true" className="text-faint">›</span>
    </Link>
  );
  return (
    <li className="grid grid-cols-1 gap-2 border-b border-navy-700/70 px-3 py-3 last:border-b-0 @2xl:grid-cols-[4.5rem_minmax(9rem,1.3fr)_repeat(3,minmax(5.5rem,1fr))_6.5rem] @2xl:items-center @2xl:gap-x-3 @2xl:py-2.5">
      <div className="flex items-center justify-between gap-2 @2xl:block">
        <span className="font-mono text-[0.72rem] text-faint">
          <span className={started ? "text-edge" : ""}>{when}</span>
          {g.neutral ? <span className="ml-2 @2xl:ml-0 @2xl:block">Neutral</span> : null}
        </span>
        <span className="@2xl:hidden">{props}</span>
      </div>
      <div className="min-w-0 space-y-1">
        {[{ t: g.away, side: "away" as const }, { t: g.home, side: "home" as const }].map(({ t, side }) => (
          <div key={side} className="flex items-center gap-2">
            <TeamBadge league={league} abbr={t.abbr} size="sm" />
            <span className="min-w-0 flex-1 truncate text-sm text-ink">
              <span className="@2xl:hidden @4xl:inline">{t.name}</span>
              <span className="hidden @2xl:inline @4xl:hidden">{nickname(t.name)}</span>
            </span>
            {!isLocked(g.projectedScore) ? <span className="font-mono text-sm text-model">{formatNumber(side === "home" ? g.projectedScore.home : g.projectedScore.away)}</span> : null}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-1.5 @2xl:contents">
        <div className={cell}>
          <div className="text-[0.62rem] text-faint">Spread</div>
          <div className="font-mono text-sm text-model">{model.text}</div>
          {market ? <div className="font-mono text-[0.7rem] text-market">{pm}{market.text}</div> : null}
          {se != null && Math.abs(se) >= 1 ? <div className={`font-mono text-[0.66rem] ${Math.abs(se) >= 3 ? "text-edge" : "text-edge/70"}`}>gap {Math.abs(se).toFixed(1)}</div> : null}
        </div>
        <div className={cell}>
          <div className="text-[0.62rem] text-faint">Total</div>
          <div className="font-mono text-sm text-model">{formatNumber(g.modelTotal)}</div>
          {mTotal != null ? <div className="font-mono text-[0.7rem] text-market">{pm}{formatNumber(mTotal)}</div> : null}
          {te != null && Math.abs(te) >= 1.5 ? <div className={`font-mono text-[0.66rem] ${Math.abs(te) >= 4 ? "text-edge" : "text-edge/70"}`}>{te > 0 ? "over" : "under"} {Math.abs(te).toFixed(1)}</div> : null}
        </div>
        <div className={cell}>
          <div className="text-[0.62rem] text-faint">Win</div>
          <Gated value={g.winProbability}>
            {(p) => <div className="font-mono text-sm text-model">{p.home >= p.away ? `${g.home.abbr} ${formatPct(p.home)}` : `${g.away.abbr} ${formatPct(p.away)}`}</div>}
          </Gated>
          {live?.homeWin != null ? (
            <div className="font-mono text-[0.7rem] text-market">PM {live.homeWin >= 0.5 ? `${g.home.abbr} ${formatPct(live.homeWin)}` : `${g.away.abbr} ${formatPct(1 - live.homeWin)}`}</div>
          ) : null}
        </div>
      </div>
      <div className="hidden text-right @2xl:block">
        {props}
        {avail?.priced ? <div className="mt-1 font-mono text-[0.65rem] text-market">{avail.priced} exchange prices</div> : null}
      </div>
      {!started ? <InjuryLine a={g.availability} changes={g.changes} league={league} home={g.home.abbr} away={g.away.abbr} quarterbacks={g.quarterbacks} /> : null}
    </li>
  );
}

/** "Chicago Bears" → "Bears"; keeps two-word nicknames that need it. */
function nickname(name: string): string {
  const two = ["Trail Blazers", "Red Wings", "Blue Jackets", "Maple Leafs", "Golden Knights"];
  return two.find((t) => name.endsWith(t)) ?? name.split(" ").slice(-1)[0];
}

/** Upcoming games as compact rows grouped by day. `day` = only that date (YYYY-MM-DD). */
export async function GameRows({ league, day, withinHours, limit, note = true, upcomingOnly = false }: { league: League; day?: string | null; withinHours?: number; limit?: number; note?: boolean; upcomingOnly?: boolean }) {
  const viewer = await getViewer();
  const [board, props] = await Promise.all([getLeagueBoard(league, viewer.tier), loadPropsBoard(league)]);
  if (!board.ok) return <Unavailable title={`${league.toUpperCase()} projections unavailable`} body={board.reason} />;
  const now = new Date().getTime(); // after the request-time board read
  const avail = new Map<string, Avail>();
  if (props.ok) {
    for (const g of props.board.games) {
      let lines = 0, priced = 0;
      for (const p of g.players) for (const m of Object.values(p.markets)) for (const t of m.thresholds) { lines++; if (t.quotes.length) priced++; }
      avail.set(g.game_id, { players: g.players.length, lines, priced });
    }
  }
  const first = board.upcoming[0]?.startTime ? Date.parse(board.upcoming[0].startTime) : null;
  let games = day ? board.upcoming.filter((g) => g.gameDate === day) : board.upcoming;
  if (!day && withinHours && first !== null) games = games.filter((g) => g.startTime && Date.parse(g.startTime) - first <= withinHours * 3600_000);
  if (upcomingOnly) games = games.filter((g) => !g.startTime || Date.parse(g.startTime) > now);
  if (limit) games = games.slice(0, limit);
  const live = (await ownerLiveMarkets()) ? await liveGameLines(league, games.filter((g) => !g.startTime || Date.parse(g.startTime) > now)) : null;
  if (!games.length) {
    const nextDay = board.upcoming.find((g) => !day || g.gameDate > day)?.gameDate;
    return (
      <Unavailable
        title={day ? "No games that day" : "No upcoming games"}
        body={nextDay ? `Next ${league.toUpperCase()} games: ${dayKey(board.upcoming.find((g) => g.gameDate === nextDay)!)}.` : "Nothing is scheduled in the projection window."}
      />
    );
  }
  const days = new Map<string, GameView[]>();
  for (const g of games) days.set(dayKey(g), [...(days.get(dayKey(g)) ?? []), g]);
  return (
    <div className="space-y-4">
      {[...days.entries()].map(([d, gs]) => (
        <section key={d}>
          <h3 className="mb-1.5 text-sm font-600 text-mute">{d}</h3>
          <ul className="@container overflow-hidden rounded-lg border border-navy-700 bg-navy-900">{gs.map((g) => <Row key={g.id} g={g} league={league} now={now} avail={avail.get(g.id)} live={live?.get(g.id)} />)}</ul>
        </section>
      ))}
      {note ? <p className="text-xs text-faint">
        Blue is the model, white the market line (favored team shown). Gaps of 3+ points on the spread or 4+ on the total are highlighted. Model {board.model.version}.
        {live ? " PM = Polymarket US main line, live (owner view on the test site only; not stored)." : ""}
      </p> : null}
    </div>
  );
}
