import Link from "next/link";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedPanel, Unavailable } from "@/components/ui/primitives";
import { formatKickoff } from "@/lib/format";
import { getExplorer, type ExplorerGame, type ExplorerQuery, type ExplorerRow } from "@/server/data/explorer";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import { browseHref, type BrowseQuery } from "./href";
import { PlayerCard } from "./PlayerCard";
import { PlayerDetail } from "./PlayerDetail";
import { listedStatus } from "./simple";

const LEAGUE_NAME: Record<League, string> = { nfl: "NFL", nba: "NBA" };

const timeOf = (g: ExplorerGame) => (g.status === "started" ? "Started" : formatKickoff(g.startTime).split(", ").slice(-1)[0]);

function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });
}

/** The day's games as one plain list. One tap gets you the players. */
export function GameList({ league, games, counts }: { league: League; games: ExplorerGame[]; counts?: Record<string, number> }) {
  if (!games.length) return <p className="text-mute">No {LEAGUE_NAME[league]} games are on the board right now.</p>;
  const days = new Map<string, ExplorerGame[]>();
  for (const g of games) days.set(g.gameDate, [...(days.get(g.gameDate) ?? []), g]);
  return (
    <div className="space-y-8">
      {[...days.entries()].map(([date, gs]) => (
        <section key={date}>
          <h2 className="mb-1 text-sm text-faint">{dayLabel(date)}</h2>
          <ul className="border-t border-navy-700">
            {gs.map((g) => (
              <li key={g.id} className="border-b border-navy-700">
                <Link href={browseHref(league, { game: g.id })} className="flex min-h-14 items-center gap-4 rounded-lg px-2 py-3 hover:bg-navy-850 sm:gap-6">
                  <span className="w-24 shrink-0 whitespace-nowrap font-mono text-sm text-mute">{timeOf(g)}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <TeamBadge league={league} abbr={g.away.abbr} size="sm" />
                    <span className="text-faint">@</span>
                    <TeamBadge league={league} abbr={g.home.abbr} size="sm" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[0.95rem] text-mute">
                    {g.away.name} at {g.home.name}
                  </span>
                  {counts?.[g.id] ? <span className="shrink-0 text-sm text-model">{counts[g.id]} players</span> : null}
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="shrink-0 text-faint"><path d="M9 6l6 6-6 6" /></svg>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/**
 * The whole league in one page: the day's games, the players inside one of them, and one player in full.
 * Three states of the same surface, so there is no menu to learn and nothing nested.
 */
export async function LeagueBrowse({ league, searchParams }: { league: League; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);
  const q: BrowseQuery = { game: one(sp.game), cat: one(sp.cat), q: one(sp.q), player: one(sp.player) };
  const viewer = await getViewer();
  const query: ExplorerQuery = { game: q.game, cat: q.cat, q: q.q, line: q.player ? `${q.player}~card` : undefined };
  const x = await getExplorer(league, viewer.tier, query);

  if (!x.ok) {
    return <Unavailable title={`${LEAGUE_NAME[league]} projections are not available`} body={x.reason} />;
  }

  // ---------------------------------------------------------------- one player, in full
  if (q.player) {
    if (isLocked(x.detail)) {
      return <LockedPanel requires={x.detail.requires} title="Player projections" body={`Player projections for ${LEAGUE_NAME[league]} are part of a paid plan.`} />;
    }
    const detail = x.detail;
    if (detail) {
      return (
        <PlayerDetail
          league={league}
          d={detail}
          catLabel={x.category.label}
          catKey={x.category.key}
          game={x.games.find((g) => g.id === detail.row.gameId) ?? x.game}
          injuries={x.injuries}
          injuryFeedAt={x.injuryFeedAt}
          backHref={browseHref(league, { game: q.game ?? x.game?.id, cat: q.cat, q: q.q })}
        />
      );
    }
    return (
      <Unavailable
        title="That player is not on the board"
        body="He may not be playing in this game, or the board may have been refreshed since the link was made."
      />
    );
  }

  // ---------------------------------------------------------------- the day's games
  if (!q.game && !q.q) {
    return (
      <div className="space-y-6">
        <GameList league={league} games={x.games} />
        <p className="text-sm text-faint">Pick a game to see every player we can project in it.</p>
      </div>
    );
  }

  // ---------------------------------------------------------------- the players in one game
  const rows: ExplorerRow[] = isLocked(x.rows) ? [] : x.rows;
  const game = x.game;

  return (
    <div className="space-y-5">
      <Link href={browseHref(league, {})} scroll={false} className="inline-flex min-h-11 items-center gap-1.5 text-sm text-mute hover:text-ink">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
        All {LEAGUE_NAME[league]} games
      </Link>

      {game ? (
        <div>
          <h1 className="font-display text-3xl font-600 leading-tight text-ink sm:text-4xl">
            {game.away.name} at {game.home.name}
          </h1>
          <p className="mt-1.5 text-sm text-mute">
            {formatKickoff(game.startTime)}
            {x.totalPlayers ? ` · ${x.totalPlayers} players projected` : ""}
          </p>
        </div>
      ) : (
        <h1 className="font-display text-3xl font-600 text-ink">Search results</h1>
      )}

      {/* other games, one tap away */}
      {x.games.length > 1 ? (
        <nav aria-label="Games" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
          {x.games.map((g) => {
            const on = g.id === game?.id && !x.searchAll;
            return (
              <Link
                key={g.id}
                href={browseHref(league, { game: g.id, cat: q.cat })}
                aria-current={on ? "page" : undefined}
                className={`flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-2 font-mono text-xs ${on ? "border-ink bg-ink text-navy-950" : "border-navy-700 text-mute hover:border-navy-600"}`}
              >
                {g.away.abbr} @ {g.home.abbr}
              </Link>
            );
          })}
        </nav>
      ) : null}

      {/* which stat, and a search box */}
      <div className="flex flex-wrap items-center gap-2">
        <nav aria-label="Stat" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
          {x.categories.map((c) => {
            const on = c.key === x.category.key;
            return (
              <Link
                key={c.key}
                href={browseHref(league, { game: q.game ?? game?.id, cat: c.key, q: q.q })}
                aria-current={on ? "page" : undefined}
                className={`shrink-0 rounded-full border px-4 py-2 text-sm ${on ? "border-ink bg-ink font-600 text-navy-950" : "border-navy-700 font-500 text-mute hover:border-navy-600"}`}
              >
                {c.label}
              </Link>
            );
          })}
        </nav>
        <form action={`/${league}`} className="ml-auto flex items-center gap-2">
          {q.game ? <input type="hidden" name="game" value={q.game} /> : null}
          {q.cat ? <input type="hidden" name="cat" value={q.cat} /> : null}
          <label htmlFor="player-search" className="sr-only">Search players</label>
          <input
            id="player-search"
            name="q"
            type="search"
            defaultValue={q.q ?? ""}
            placeholder="Search players"
            className="min-h-11 w-48 rounded-lg border border-navy-700 bg-navy-900 px-3.5 text-[0.95rem] text-ink placeholder:text-faint focus:border-model focus:outline-none"
          />
          <button type="submit" className="min-h-11 rounded-lg border border-navy-700 px-4 text-sm font-500 text-mute hover:border-model hover:text-ink">Search</button>
        </form>
      </div>

      {isLocked(x.rows) ? (
        <LockedPanel requires={x.rows.requires} title="Player projections" body={`Player projections for ${LEAGUE_NAME[league]} are part of a paid plan.`} />
      ) : rows.length === 0 ? (
        <Unavailable
          title="No players match"
          body={q.q ? `Nothing matched "${q.q}" in ${x.category.label.toLowerCase()}. Try another spelling, or clear the search.` : `No ${x.category.label.toLowerCase()} projections are published for this game.`}
        />
      ) : (
        <>
          <p className="text-sm text-faint">
            {rows.some((r) => r.headline?.quotes.length)
              ? "Where a sportsbook line is published we show it beside our number."
              : "No sportsbook line is published for these props, so every number here is our own."}
          </p>
          <div className="space-y-2.5">
            {rows.map((r) => (
              <PlayerCard
                key={r.id}
                league={league}
                r={r}
                catLabel={x.category.label}
                href={browseHref(league, { game: q.game ?? r.gameId, cat: q.cat, q: q.q, player: r.id })}
                listed={listedStatus(x.injuries, r)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
