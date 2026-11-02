import Link from "next/link";
import { Suspense, type CSSProperties } from "react";
import { favoredLine, formatKickoff, formatNumber } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { isLocked, type GameView } from "@/types/domain";

export function Hero() {
  return (
    <section className="mx-auto grid max-w-7xl items-center gap-12 px-4 pb-10 pt-12 sm:px-6 sm:pt-20 lg:grid-cols-[1fr_1.05fr]">
      <div>
        <h1 className="font-display text-[3.2rem] font-700 leading-[0.92] tracking-tight text-ink sm:text-[4.6rem]">
          Where the market and the model disagree.
        </h1>
        <p className="mt-5 max-w-lg text-lg leading-relaxed text-mute">
          Model Room projects every NFL and NBA spread and total from play-by-play and box-score data, then shows the gap against the posted line.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/nfl" className="rounded-full bg-model px-5 py-2.5 font-600 text-navy-950 hover:bg-model/90">
            Open the NFL board
          </Link>
          <Link href="/nba" className="rounded-full border border-navy-600 px-5 py-2.5 font-600 text-ink hover:border-mute">
            Open the NBA board
          </Link>
        </div>
      </div>
      <Suspense fallback={<div className="h-[300px] rounded-2xl border border-navy-700 bg-navy-900" />}>
        <FeaturedGame />
      </Suspense>
    </section>
  );
}

/** The upcoming game with the largest visible spread edge; else the next game with a projection. */
async function FeaturedGame() {
  const viewer = await getViewer();
  const boards = await Promise.all([getLeagueBoard("nfl", viewer.tier), getLeagueBoard("nba", viewer.tier)]);
  const games = boards.flatMap((b) => (b.ok ? b.upcoming : []));
  const withEdge = games
    .filter((g) => g.market?.spread != null && !isLocked(g.spreadEdge) && g.spreadEdge !== null)
    .sort((a, b) => Math.abs(b.spreadEdge as number) - Math.abs(a.spreadEdge as number));
  const pick = withEdge[0] ?? games.sort((a, b) => (a.startTime ?? "").localeCompare(b.startTime ?? ""))[0];
  if (!pick) {
    return (
      <figure className="rounded-2xl border border-navy-700 bg-navy-900 p-7">
        <figcaption className="font-display text-xl font-600 text-ink">No projections yet</figcaption>
        <p className="mt-2 text-mute">Run the engines to generate this week&rsquo;s projections.</p>
      </figure>
    );
  }
  return pick.market?.spread != null && !isLocked(pick.spreadEdge) ? <EdgeFigure g={pick} /> : <ModelFigure g={pick} />;
}

function Caption({ g, note }: { g: GameView; note: string }) {
  return (
    <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
      <span className="font-display text-xl font-600 text-ink">
        {g.away.name} <span className="text-faint">at</span> {g.home.name}
      </span>
      <span className="text-sm text-mute">
        {g.league.toUpperCase()}, {formatKickoff(g.startTime)}. {note}
      </span>
    </figcaption>
  );
}

/** Market vs model on a number line, both as the home team's line. */
function EdgeFigure({ g }: { g: GameView }) {
  const market = g.market!.spread!;
  const model = g.modelSpread;
  const lo = Math.floor(Math.min(market, model, 0) - 2);
  const hi = Math.ceil(Math.max(market, model, 0) + 2);
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const edge = Math.abs(market - model);
  const side = market - model > 0 ? g.home.abbr : g.away.abbr;
  const mk = favoredLine(market, g.home.abbr, g.away.abbr);
  const md = favoredLine(model, g.home.abbr, g.away.abbr);
  const left = Math.min(pos(market), pos(model));
  // Keep a label inside the track near either end instead of centring it off the edge.
  const anchor = (x: number) => ({ left: `${x}%`, "--mx": x > 82 ? "-100%" : x < 18 ? "0%" : "-50%", transform: "translateX(var(--mx))", textAlign: x > 82 ? "right" : x < 18 ? "left" : "center" }) as CSSProperties;
  const width = Math.abs(pos(market) - pos(model));

  return (
    <figure className="rounded-2xl border border-navy-700 bg-navy-900 p-5 sm:p-7">
      <Caption g={g} note={`Market line from ${g.market!.sources.join(", ")}`} />
      <div className="relative mt-14 h-28" role="img" aria-label={`Market ${mk.text}, model ${md.text}, a ${edge.toFixed(1)} point gap.`}>
        <div className="gap-marker absolute -top-10 whitespace-nowrap" style={anchor(pos(market))}>
          <div className="text-[0.8rem] text-mute">Market</div>
          <div className="font-display text-2xl font-700 leading-none text-market sm:text-3xl">{mk.text}</div>
        </div>
        <div className="gap-marker absolute top-[3.6rem] whitespace-nowrap" style={anchor(pos(model))}>
          <div className="font-display text-2xl font-700 leading-none text-model sm:text-3xl">{md.text}</div>
          <div className="text-[0.8rem] text-mute">Model</div>
        </div>
        <div className="absolute left-0 right-0 top-9 h-1 rounded-full bg-navy-700" />
        <div className="gap-bar absolute top-[2.05rem] h-2.5 rounded-full bg-edge" style={{ left: `${left}%`, width: `${width}%` }} />
        <div className="absolute top-[1.9rem] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-navy-900 bg-market" style={{ left: `${pos(market)}%` }} />
        <div className="absolute top-[1.9rem] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-navy-900 bg-model" style={{ left: `${pos(model)}%` }} />
      </div>
      <div className="gap-marker-late mt-2 flex items-end justify-between gap-4 border-t border-navy-700 pt-4">
        <div>
          <div className="font-display text-5xl font-700 leading-none text-edge">{edge.toFixed(1)}</div>
          <div className="mt-1 text-sm text-mute">point gap toward {side}</div>
        </div>
        <p className="max-w-[17rem] text-right text-sm leading-relaxed text-mute">
          The model projects {formatNumber(Math.abs(g.projectedMargin))} points for {g.projectedMargin >= 0 ? g.home.abbr : g.away.abbr}. The market says {formatNumber(Math.abs(market))}.
        </p>
      </div>
    </figure>
  );
}

/** No market line: the model's own call. */
function ModelFigure({ g }: { g: GameView }) {
  const md = favoredLine(g.modelSpread, g.home.abbr, g.away.abbr);
  return (
    <figure className="rounded-2xl border border-navy-700 bg-navy-900 p-5 sm:p-7">
      <Caption g={g} note="No market line connected" />
      <div className="mt-8 grid grid-cols-2 gap-6">
        <div>
          <div className="text-sm text-mute">Model line</div>
          <div className="font-display text-5xl font-700 leading-none text-model">{md.text}</div>
        </div>
        <div>
          <div className="text-sm text-mute">Model total</div>
          <div className="font-display text-5xl font-700 leading-none text-model">{formatNumber(g.modelTotal)}</div>
        </div>
      </div>
      <p className="mt-6 border-t border-navy-700 pt-4 text-sm text-mute">
        Edges appear once a market line is connected for this game.
      </p>
    </figure>
  );
}
