import Link from "next/link";

/**
 * Hero: the gap between the market line and the model line, drawn on a
 * number line. Static illustration using the demo slate's first game.
 */
const MIN = -9;
const MAX = 0;
const MARKET = -3.5;
const MODEL = -6.0;
const pos = (v: number) => ((v - MIN) / (MAX - MIN)) * 100;

export function Hero() {
  const left = pos(MODEL);
  const width = pos(MARKET) - pos(MODEL);
  const ticks = [-9, -7.5, -6, -4.5, -3, -1.5, 0];

  return (
    <section className="mx-auto grid max-w-7xl items-center gap-12 px-4 pb-10 pt-12 sm:px-6 sm:pt-20 lg:grid-cols-[1fr_1.05fr]">
      <div>
        <h1 className="font-display text-[3.2rem] font-700 leading-[0.92] tracking-tight text-ink sm:text-[4.6rem]">
          Where the market and the model disagree.
        </h1>
        <p className="mt-5 max-w-lg text-lg leading-relaxed text-mute">
          Model Room projects every NFL and NBA spread and total, then shows you the gap against the posted line.
          Injuries, props and team ratings sit on the same board.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/nfl" className="rounded-full bg-model px-5 py-2.5 font-600 text-navy-950 hover:bg-model/90">
            Open the NFL board
          </Link>
          <Link
            href="/nba"
            className="rounded-full border border-navy-600 px-5 py-2.5 font-600 text-ink hover:border-mute"
          >
            Open the NBA board
          </Link>
        </div>
      </div>

      <figure className="rounded-2xl border border-navy-700 bg-navy-900 p-5 sm:p-7">
        <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="font-display text-xl font-600 text-ink">
            Boise <span className="text-faint">at</span> Albany
          </span>
          <span className="text-sm text-edge">Demo example with fictional teams</span>
        </figcaption>

        <div className="relative mt-14 h-28" role="img" aria-label={`Albany spread: market ${MARKET}, model ${MODEL}. Gap of 2.5 points.`}>
          {/* market marker above the line */}
          <div className="gap-marker absolute -top-10 text-center" style={{ left: `${pos(MARKET)}%`, transform: "translateX(-50%)" }}>
            <div className="text-[0.8rem] text-mute">Market</div>
            <div className="font-display text-3xl font-700 leading-none text-market">{MARKET}</div>
          </div>
          {/* model marker below the line */}
          <div className="gap-marker absolute top-[3.6rem] text-center" style={{ left: `${pos(MODEL)}%`, transform: "translateX(-50%)" }}>
            <div className="font-display text-3xl font-700 leading-none text-model">{MODEL.toFixed(1)}</div>
            <div className="text-[0.8rem] text-mute">Model</div>
          </div>

          {/* the line */}
          <div className="absolute left-0 right-0 top-9 h-1 rounded-full bg-navy-700" />
          {ticks.map((t) => (
            <div key={t} className="absolute top-[2.15rem] h-3 w-px bg-navy-600" style={{ left: `${pos(t)}%` }} />
          ))}
          {/* the gap */}
          <div className="gap-bar absolute top-[2.05rem] h-2.5 rounded-full bg-edge" style={{ left: `${left}%`, width: `${width}%` }} />
          <div className="absolute top-[1.9rem] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-navy-900 bg-market" style={{ left: `${pos(MARKET)}%` }} />
          <div className="absolute top-[1.9rem] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-navy-900 bg-model" style={{ left: `${pos(MODEL)}%` }} />
        </div>

        <div className="gap-marker-late mt-2 flex items-end justify-between gap-4 border-t border-navy-700 pt-4">
          <div>
            <div className="font-display text-5xl font-700 leading-none text-edge">2.5</div>
            <div className="mt-1 text-sm text-mute">point edge on Albany</div>
          </div>
          <p className="max-w-[16rem] text-right text-sm leading-relaxed text-mute">
            The model has Albany winning by 6. The market says 3.5. That gap is what the Edge Finder ranks.
          </p>
        </div>
      </figure>
    </section>
  );
}
