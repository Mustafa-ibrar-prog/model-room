import Link from "next/link";
import { favoredLine, formatKickoff, formatNumber, formatPct } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameView, type League } from "@/types/domain";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { Gated, Unavailable } from "@/components/ui/primitives";

function dayKey(iso: string | null, fallback: string): string {
  if (!iso) return fallback;
  return new Date(iso).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "America/New_York" });
}

function Card({ g, league, now }: { g: GameView; league: League; now: number }) {
  const model = favoredLine(g.modelSpread, g.home.abbr, g.away.abbr);
  const market = g.market?.spread != null ? favoredLine(g.market.spread, g.home.abbr, g.away.abbr) : null;
  const started = g.startTime ? Date.parse(g.startTime) <= now : false;
  const spreadEdge = !isLocked(g.spreadEdge) ? g.spreadEdge : null;
  const totalEdge = !isLocked(g.totalEdge) ? g.totalEdge : null;
  const notes = [
    g.rest.awayB2b && `${g.away.abbr} back-to-back`,
    g.rest.homeB2b && `${g.home.abbr} back-to-back`,
    g.neutral && "Neutral site",
    g.quarterbacks && (g.quarterbacks.away || g.quarterbacks.home) && `${g.quarterbacks.away ?? "TBD"} vs ${g.quarterbacks.home ?? "TBD"}`,
  ].filter(Boolean) as string[];
  return (
    <li className="flex flex-col rounded-lg border border-navy-700 bg-navy-900">
      <div className="flex items-center justify-between border-b border-navy-700/70 px-4 py-2 text-xs">
        <span className="font-mono text-mute">{formatKickoff(g.startTime).split(", ").slice(-1)[0]}</span>
        <span className={`rounded-sm px-1.5 py-px font-mono uppercase tracking-wider ${started ? "bg-edge/15 text-edge" : "text-faint"}`}>{started ? "Started" : "Upcoming"}</span>
      </div>
      <div className="space-y-2 px-4 py-3">
        {[{ t: g.away, side: "away" as const }, { t: g.home, side: "home" as const }].map(({ t, side }) => (
          <div key={side} className="flex items-center gap-2.5">
            <TeamBadge league={league} abbr={t.abbr} />
            <span className="min-w-0 flex-1 truncate text-[0.95rem] text-ink">{t.name}</span>
            <Gated value={g.projectedScore}>{(s) => <span className="font-display text-xl font-600 text-model">{formatNumber(side === "home" ? s.home : s.away)}</span>}</Gated>
          </div>
        ))}
      </div>
      <dl className="grid grid-cols-3 gap-2 border-t border-navy-700/70 px-4 py-3 text-center">
        <div>
          <dt className="font-mono text-[0.65rem] uppercase tracking-wider text-faint">Model</dt>
          <dd className="font-display text-lg font-600 text-model">{model.text}</dd>
          <dd className="font-mono text-xs text-mute">o/u {formatNumber(g.modelTotal)}</dd>
        </div>
        <div>
          <dt className="font-mono text-[0.65rem] uppercase tracking-wider text-faint">Market</dt>
          <dd className="font-display text-lg font-600 text-market">{market ? market.text : "–"}</dd>
          <dd className="font-mono text-xs text-mute">{g.market?.total != null ? `o/u ${formatNumber(g.market.total)}` : "not posted"}</dd>
        </div>
        <div>
          <dt className="font-mono text-[0.65rem] uppercase tracking-wider text-faint">Win %</dt>
          <dd className="font-display text-lg font-600 text-ink">
            <Gated value={g.winProbability}>{(p) => <span>{p.home >= p.away ? `${g.home.abbr} ${formatPct(p.home)}` : `${g.away.abbr} ${formatPct(p.away)}`}</span>}</Gated>
          </dd>
        </div>
      </dl>
      <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-navy-700/70 px-4 py-2.5">
        {isLocked(g.spreadEdge) ? (
          <Gated value={g.spreadEdge}>{() => null}</Gated>
        ) : spreadEdge != null && Math.abs(spreadEdge) >= 1 ? (
          <span className={`rounded px-1.5 py-0.5 font-mono text-xs ${Math.abs(spreadEdge) >= 3 ? "bg-edge text-navy-950" : "border border-edge/60 text-edge"}`}>
            Side {spreadEdge > 0 ? g.home.abbr : g.away.abbr} {Math.abs(spreadEdge).toFixed(1)}
          </span>
        ) : null}
        {totalEdge != null && Math.abs(totalEdge) >= 1.5 ? (
          <span className={`rounded px-1.5 py-0.5 font-mono text-xs ${Math.abs(totalEdge) >= 4 ? "bg-edge text-navy-950" : "border border-edge/60 text-edge"}`}>
            {totalEdge > 0 ? "Over" : "Under"} {Math.abs(totalEdge).toFixed(1)}
          </span>
        ) : null}
        {notes.length ? <span className="text-xs text-faint">{notes.join(" · ")}</span> : null}
        <Link href={`/props?sport=${league}&game=${encodeURIComponent(g.id)}`} className="ml-auto text-sm font-600 text-model hover:underline">Props</Link>
      </div>
    </li>
  );
}

/** Upcoming games as cards, grouped by day. */
export async function GameCards({ league, withinHours }: { league: League; withinHours?: number }) {
  const viewer = await getViewer();
  const board = await getLeagueBoard(league, viewer.tier);
  if (!board.ok) return <Unavailable title={`${league.toUpperCase()} projections unavailable`} body={board.reason} />;
  const now = new Date().getTime(); // after the request-time board read
  const first = board.upcoming[0]?.startTime ? Date.parse(board.upcoming[0].startTime) : null;
  const games = withinHours && first !== null ? board.upcoming.filter((g) => g.startTime && Date.parse(g.startTime) - first <= withinHours * 3600_000) : board.upcoming;
  if (!games.length) return <Unavailable title="No upcoming games" body="Nothing is scheduled in the projection window." />;
  const days = new Map<string, GameView[]>();
  for (const g of games) {
    const k = dayKey(g.startTime, g.gameDate);
    days.set(k, [...(days.get(k) ?? []), g]);
  }
  return (
    <div className="space-y-6">
      {[...days.entries()].map(([day, gs]) => (
        <section key={day}>
          <h3 className="mb-2 font-mono text-xs uppercase tracking-widest text-faint">{day}</h3>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{gs.map((g) => <Card key={g.id} g={g} league={league} now={now} />)}</ul>
        </section>
      ))}
      <p className="text-xs text-faint">
        Model {board.model.version}. Lines are shown for the favored team. Side and total edges are the model&apos;s gap to the market line in points; the
        solid ones are 3+ points on the side or 4+ on the total.
      </p>
    </div>
  );
}
