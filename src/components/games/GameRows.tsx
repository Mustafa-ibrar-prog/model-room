import Link from "next/link";
import { favoredLine, formatKickoff, formatNumber, formatPct } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { loadPropsBoard } from "@/server/engine/board";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameView, type League } from "@/types/domain";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { Gated, Unavailable } from "@/components/ui/primitives";

function dayKey(g: GameView): string {
  const [y, m, d] = g.gameDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" });
}

type Avail = { players: number; lines: number; priced: number };

function Row({ g, league, now, avail }: { g: GameView; league: League; now: number; avail: Avail | undefined }) {
  const model = favoredLine(g.modelSpread, g.home.abbr, g.away.abbr);
  const market = g.market?.spread != null ? favoredLine(g.market.spread, g.home.abbr, g.away.abbr) : null;
  const started = g.startTime ? Date.parse(g.startTime) <= now : false;
  const se = !isLocked(g.spreadEdge) ? g.spreadEdge : null;
  const te = !isLocked(g.totalEdge) ? g.totalEdge : null;
  const cell = "rounded-md bg-navy-850 px-2 py-1.5 text-center";
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-2 border-b border-navy-700/70 px-3 py-2.5 last:border-b-0 @2xl:grid-cols-[4.5rem_minmax(10rem,1.3fr)_repeat(3,minmax(5.5rem,1fr))_7rem]">
      <div className="order-first col-span-2 flex items-center gap-2 font-mono text-[0.72rem] text-faint @2xl:col-span-1 @2xl:block">
        <span className={started ? "text-edge" : ""}>{started ? "Started" : formatKickoff(g.startTime).split(", ").slice(-1)[0]}</span>
        {g.neutral ? <span className="@2xl:block">Neutral</span> : null}
      </div>
      <div className="min-w-0 space-y-1">
        {[{ t: g.away, side: "away" as const }, { t: g.home, side: "home" as const }].map(({ t, side }) => (
          <div key={side} className="flex items-center gap-2">
            <TeamBadge league={league} abbr={t.abbr} size="sm" />
            <span className="min-w-0 flex-1 truncate text-sm text-ink">{t.name}</span>
            {!isLocked(g.projectedScore) ? <span className="font-mono text-sm text-model">{formatNumber(side === "home" ? g.projectedScore.home : g.projectedScore.away)}</span> : null}
          </div>
        ))}
      </div>
      <div className="col-span-2 grid grid-cols-3 gap-1.5 @2xl:contents">
        <div className={cell}>
          <div className="text-[0.62rem] text-faint">Spread</div>
          <div className="font-mono text-sm text-model">{model.text}</div>
          <div className={`font-mono text-[0.7rem] ${market ? "text-market" : "text-faint"}`}>{market ? market.text : "no line"}</div>
          {se != null && Math.abs(se) >= 1 ? <div className={`font-mono text-[0.66rem] ${Math.abs(se) >= 3 ? "text-edge" : "text-edge/70"}`}>gap {Math.abs(se).toFixed(1)}</div> : null}
        </div>
        <div className={cell}>
          <div className="text-[0.62rem] text-faint">Total</div>
          <div className="font-mono text-sm text-model">{formatNumber(g.modelTotal)}</div>
          <div className={`font-mono text-[0.7rem] ${g.market?.total != null ? "text-market" : "text-faint"}`}>{g.market?.total != null ? formatNumber(g.market.total) : "no line"}</div>
          {te != null && Math.abs(te) >= 1.5 ? <div className={`font-mono text-[0.66rem] ${Math.abs(te) >= 4 ? "text-edge" : "text-edge/70"}`}>{te > 0 ? "over" : "under"} {Math.abs(te).toFixed(1)}</div> : null}
        </div>
        <div className={cell}>
          <div className="text-[0.62rem] text-faint">Win</div>
          <Gated value={g.winProbability}>
            {(p) => <div className="font-mono text-sm text-model">{p.home >= p.away ? `${g.home.abbr} ${formatPct(p.home)}` : `${g.away.abbr} ${formatPct(p.away)}`}</div>}
          </Gated>
        </div>
      </div>
      <div className="col-span-2 flex items-center justify-between gap-2 @2xl:col-span-1 @2xl:block @2xl:text-right">
        <Link href={`/props?sport=${league}&game=${encodeURIComponent(g.id)}`} className="inline-block rounded-full bg-navy-800 px-3 py-1 text-sm font-600 text-ink hover:bg-navy-700">
          Props{avail?.players ? ` · ${avail.players}` : ""}
        </Link>
        <div className="font-mono text-[0.65rem] text-faint @2xl:mt-1">{avail?.priced ? <span className="text-market">{avail.priced} exchange prices</span> : "no exchange prices"}</div>
      </div>
    </li>
  );
}

/** Upcoming games as compact rows grouped by day. `day` = only that date (YYYY-MM-DD). */
export async function GameRows({ league, day, withinHours, limit, note = true }: { league: League; day?: string | null; withinHours?: number; limit?: number; note?: boolean }) {
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
  if (limit) games = games.slice(0, limit);
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
          <ul className="@container overflow-hidden rounded-lg border border-navy-700 bg-navy-900">{gs.map((g) => <Row key={g.id} g={g} league={league} now={now} avail={avail.get(g.id)} />)}</ul>
        </section>
      ))}
      {note ? <p className="text-xs text-faint">
        Teal is the model, blue the market line (favored team shown). Gaps of 3+ points on the spread or 4+ on the total are highlighted. Model {board.model.version}.
      </p> : null}
    </div>
  );
}
