import Link from "next/link";
import { Suspense } from "react";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { DataSources } from "@/components/marketing/DataSources";
import { GameList } from "@/components/league/Browse";
import { TableSkeleton } from "@/components/ui/primitives";
import { getExplorer } from "@/server/data/explorer";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";

type SP = Promise<Record<string, string | string[] | undefined>>;

/**
 * The home page is the day's games and nothing else. Pick one and you are in the players; everything
 * deeper is behind that. The explainers stay underneath for a first-time visitor.
 */
export default function HomePage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <div className="mx-auto w-full max-w-5xl px-4 pb-12 pt-8 sm:px-6">
        <Suspense fallback={<TableSkeleton rows={6} />}>
          <Today searchParams={searchParams} />
        </Suspense>
      </div>
      <HowItWorks />
      <DataSources />
    </>
  );
}

async function Today({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const asked = typeof sp.sport === "string" && (sp.sport === "nba" || sp.sport === "nfl") ? (sp.sport as League) : null;
  const viewer = await getViewer();
  const [nba, nfl] = await Promise.all([getExplorer("nba", viewer.tier, {}), getExplorer("nfl", viewer.tier, {})]);
  const boards = { nba, nfl } as const;
  const count = (l: League) => (boards[l].ok ? boards[l].games.length : 0);
  const soonest = (l: League) => {
    const b = boards[l];
    if (!b.ok) return Infinity;
    const times = b.games.map((g) => (g.startTime ? Date.parse(g.startTime) : Infinity)).filter((t) => Number.isFinite(t));
    return times.length ? Math.min(...times) : Infinity;
  };
  const league: League = asked ?? (soonest("nba") <= soonest("nfl") ? "nba" : "nfl");
  const board = boards[league];

  return (
    <div className="space-y-7">
      <div>
        <h1 className="font-display text-4xl font-600 leading-none text-ink sm:text-5xl">Today&apos;s games</h1>
        <p className="mt-3 max-w-xl text-[1.05rem] leading-relaxed text-mute">
          Pick a game for the model&apos;s prediction, or go straight to player props.
        </p>
      </div>

      <nav aria-label="Sections" className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {[
          { href: "/nba-props", title: "NBA Props", sub: "Points, rebounds, assists, threes" },
          { href: "/nfl-props", title: "NFL Props", sub: "Passing, rushing, receiving, TDs" },
          { href: "/nba", title: "NBA", sub: "Winner, score, total, spread" },
          { href: "/nfl", title: "NFL", sub: "Winner, score, total, spread" },
        ].map((x) => (
          <Link key={x.href} href={x.href} className="rounded-xl bg-navy-900 p-4 hover:bg-navy-850">
            <span className="block font-display text-xl font-700 text-ink">{x.title}</span>
            <span className="mt-0.5 block text-xs text-mute">{x.sub}</span>
          </Link>
        ))}
      </nav>

      <div className="flex flex-wrap items-center gap-2.5">
        {(["nba", "nfl"] as const).map((l) => {
          const on = l === league;
          return (
            <Link
              key={l}
              href={`/?sport=${l}`}
              aria-current={on ? "page" : undefined}
              className={`rounded-full px-5 py-2.5 text-[0.95rem] ${on ? "bg-ink font-600 text-navy-950" : "border border-navy-700 font-500 text-mute hover:border-navy-600"}`}
            >
              {l.toUpperCase()} <span className={on ? "font-400 opacity-60" : "text-faint"}>{count(l)} games</span>
            </Link>
          );
        })}
        <form action={`/${league}-props`} className="ml-auto flex items-center gap-2">
          <label htmlFor="home-search" className="sr-only">Search players</label>
          <input
            id="home-search"
            name="q"
            type="search"
            placeholder="Search any player"
            className="min-h-11 w-52 rounded-lg border border-navy-700 bg-navy-900 px-3.5 text-[0.95rem] text-ink placeholder:text-faint focus:border-model focus:outline-none"
          />
          <button type="submit" className="min-h-11 rounded-lg border border-navy-700 px-4 text-sm font-500 text-mute hover:border-model hover:text-ink">Search</button>
        </form>
      </div>

      {board.ok ? (
        <GameList league={league} games={board.games} to="games" />
      ) : (
        <p className="text-mute">{board.reason}</p>
      )}

      <p className="text-sm text-faint">
        Model Room projects players and games. It does not tell you what to bet, and it does not claim to beat the market.
      </p>
    </div>
  );
}
