import Link from "next/link";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell } from "@/components/ui/primitives";
import { fmt } from "@/components/market/bits";
import { formatProjection } from "@/lib/format";
import { bookTime } from "@/components/league/PlayerCard";

const american = (o: number | null) => (o == null ? "—" : o > 0 ? `+${o}` : `${o}`);
import { Section, InjurySection, MatchupSection, type InjuryFeed } from "@/components/market/AnalysisSections";
import { Contributions, DistributionChart } from "@/components/market/PropParts";
import { HistoryTabs, type HistoryTabsData } from "@/components/market/HistoryTabs";
import { formatKickoff, formatPct } from "@/lib/format";
import { seasonLabel, type ContractDetail, type ExplorerGame } from "@/server/data/explorer";
import { isLocked, type League } from "@/types/domain";
import { headlineFor, historyCaveat, listedStatus, listedText, playerSub, projText } from "./simple";

/**
 * One player, in full. The answer sits at the top in the largest type on the page; everything else is
 * five closed sections the reader opens if they want them. Nothing is recalculated here and nothing is
 * invented: where a figure is not published, or is part of a paid plan, the section says so.
 */
export function PlayerDetail({
  league,
  d,
  catLabel,
  catKey,
  game,
  injuries,
  injuryFeedAt,
  backHref,
}: {
  league: League;
  d: ContractDetail;
  catLabel: string;
  catKey: string;
  game: ExplorerGame | null;
  injuries: InjuryFeed;
  injuryFeedAt: string | null;
  backHref: string;
}) {
  const r = d.row;
  const h = headlineFor(r);
  const caveat = historyCaveat(r);
  const contrib = isLocked(r.contributions) ? null : r.contributions;
  const hist = r.history;
  const seasonText = seasonLabel(league, hist.boardSeason);
  const pct = h ? Math.round(h.prob * 100) : null;
  const inj = r.injury?.status && r.injury.status !== "available" ? r.injury : null;
  const listed = inj ? null : listedStatus(injuries, r);

  const histData: HistoryTabsData = {
    stat: catLabel,
    games: hist.games,
    published: hist.published,
    boardSeason: hist.boardSeason,
    seasonText,
    season: hist.season ? { games: hist.season.games, avg: hist.season.avg, opportunity: hist.season.opportunity } : null,
    opportunity: hist.opportunity,
    clear: h ? { k: h.threshold, op: ">=", label: `${h.threshold}+` } : null,
    seasonNames: Object.fromEntries(
      [...new Set(hist.games.map((g) => g.season).filter((s): s is number => s != null))].map((s) => [s, seasonLabel(league, s)]),
    ),
  };
  const played = hist.games.filter((g) => g.value != null).slice(0, 10);
  const cleared = h ? played.filter((g) => (g.value ?? 0) >= h.threshold).length : null;
  const last10Summary = !played.length
    ? "no past games published"
    : cleared !== null && h
      ? `cleared ${h.threshold} in ${cleared} of ${played.length}`
      : `last ${played.length}`;
  const season = hist.season;

  return (
    <div className="space-y-5">
      <Link href={backHref} scroll={false} className="inline-flex min-h-11 items-center gap-1.5 text-sm text-mute hover:text-ink">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
        {game ? `${game.away.name} at ${game.home.name}` : "All players"}
      </Link>

      <div className="flex items-start gap-3">
        <TeamBadge league={league} abbr={r.team} />
        <div className="min-w-0">
          <h1 className="font-display text-4xl font-600 leading-none text-ink sm:text-5xl">{r.name}</h1>
          <p className="mt-2 text-sm text-mute">
            {playerSub(r)}
            {game?.startTime ? ` · ${formatKickoff(game.startTime)}` : ""}
          </p>
        </div>
      </div>

      {inj ? (
        <p className="text-sm text-edge">
          {inj.lateScratch ? "Late scratch: " : ""}
          {inj.rawStatus ?? inj.status} &middot; {inj.confirmed ? "official report" : "reported, not yet official"}
        </p>
      ) : null}

      {listed ? <p className="rounded-lg bg-navy-900 px-4 py-3 text-sm text-edge">{listedText(listed)}</p> : null}

      {/* the answer */}
      <section aria-label="Projection" className="rounded-2xl bg-navy-900 p-5 sm:p-7">
        {h && pct !== null ? (
          <div className="flex flex-wrap items-start gap-x-12 gap-y-6">
            <div className="min-w-0 flex-[1_1_16rem]">
              <p className="text-sm text-mute">Chance of {h.thresholdText} {catLabel.toLowerCase()}</p>
              <p className="font-display text-7xl font-700 leading-none text-ink sm:text-8xl">{pct}%</p>
              <div className="mt-4 h-2.5 max-w-xs overflow-hidden rounded-full bg-navy-600" aria-hidden="true">
                <div className="h-full bg-model" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-2 text-sm text-mute">
                And {formatPct(h.belowProb)} {h.belowText}.
              </p>
            </div>

            <dl className="grid min-w-0 flex-[1_1_auto] grid-cols-3 gap-4 sm:flex sm:flex-wrap sm:gap-x-10 sm:gap-y-6">
              <div>
                <dt className="text-xs text-faint">Sportsbook line</dt>
                {h.fromMarket ? (
                  <>
                    <dd className="font-display text-3xl font-600 leading-none text-market">{h.threshold}</dd>
                    {h.marketProb != null ? <p className="mt-1.5 hidden max-w-[20ch] text-xs text-mute sm:block">{h.book ? "Books, margin removed" : "The market"}: {formatPct(h.marketProb)} over.</p> : null}
                  </>
                ) : (
                  <>
                    <dd className={`font-display text-3xl font-600 leading-none ${r.lineStatus?.state === "pending" ? "text-pending" : "text-faint"}`}>{r.lineStatus ? r.lineStatus.label : "none"}</dd>
                    <p className="mt-1.5 hidden max-w-[22ch] text-xs text-mute sm:block">{r.lineStatus ? `${r.lineStatus.reason} ` : ""}The threshold above is our own.</p>
                  </>
                )}
              </div>
              <div>
                <dt className="text-xs text-faint">We project</dt>
                <dd className="font-display text-3xl font-600 leading-none text-model">{projText(r)}</dd>
                <p className="mt-1.5 hidden max-w-[22ch] text-xs text-mute sm:block">
                  In 8 games out of 10 he lands between {formatProjection(r.range80[0])} and {formatProjection(r.range80[1])}.
                </p>
              </div>
              <div>
                <dt className="text-xs text-faint">Side we prefer</dt>
                <dd className="font-display text-3xl font-600 leading-none text-faint">&mdash;</dd>
                <p className="mt-1.5 hidden max-w-[22ch] text-xs text-mute sm:block">We only call a side against a published line.</p>
              </div>
            </dl>
          </div>
        ) : (
          <p className="text-mute">No projection is published for {r.name} in {catLabel.toLowerCase()}.</p>
        )}
        {h && !h.fromMarket ? (
          <p className="mt-4 text-xs text-mute sm:hidden">
            {r.lineStatus ? `Sportsbook line ${r.lineStatus.label.toLowerCase()}: ${r.lineStatus.reason}` : "No sportsbook line is stored for this prop."} The threshold is our own and we call no side. In 8 games out of 10 he lands between {formatProjection(r.range80[0])} and {formatProjection(r.range80[1])}.
          </p>
        ) : null}
        {h?.book ? (
          <div className="mt-6">
            <p className="text-xs text-faint">Sportsbook lines (points, US books) · captured {bookTime(h.book.capturedAt)} · consensus is the middle of the books&apos; main lines</p>
            <table className="mt-2 w-full max-w-lg text-sm">
              <thead>
                <tr className="text-left text-xs text-faint">
                  <th className="py-1 font-400">Sportsbook</th><th className="py-1 font-400">Line</th><th className="py-1 font-400">Over</th><th className="py-1 font-400">Under</th><th className="py-1 font-400">Updated</th>
                </tr>
              </thead>
              <tbody>
                {h.book.books.map((b) => (
                  <tr key={b.title} className="border-t border-navy-800">
                    <td className="py-1.5 text-ink">{b.title}</td>
                    <td className="py-1.5 tabular-nums text-market">{b.line}</td>
                    <td className="py-1.5 tabular-nums text-mute">{american(b.over)}</td>
                    <td className="py-1.5 tabular-nums text-mute">{american(b.under)}</td>
                    <td className="py-1.5 text-faint">{bookTime(b.lastUpdate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[0.7rem] leading-snug text-faint">
              {h.book.alternates ? `${h.book.alternates} alternate line${h.book.alternates > 1 ? "s" : ""} kept on record, not shown. ` : ""}
              Lines from The Odds API as captured, not live; the model never reads them. Gamble responsibly. 18+.
            </p>
          </div>
        ) : null}
        {caveat ? <p className="mt-5 text-sm text-edge">{caveat}</p> : null}
      </section>

      {/* everything else, closed */}
      <div>
        <Section title="Last 10 games" summary={last10Summary}>
          <HistoryTabs d={histData} />
        </Section>

        <InjurySection league={league} r={r} feed={injuries} feedAt={injuryFeedAt} title="Injuries" />

        <MatchupSection league={league} r={r} cat={catKey} contributions={contrib} title="Matchup" />

        <Section title="How we got this number" summary={contrib?.steps ? `${contrib.steps.length} steps` : isLocked(r.contributions) ? "Pro" : "final only"}>
          <div className="space-y-2">
            <h4 className="text-[0.68rem] text-faint">From what he usually does to what we expect tonight</h4>
            {isLocked(r.contributions) ? (
              <div className="flex items-center gap-2 text-faint">
                <span>The model&apos;s step-by-step record is part of Pro.</span>
                <LockedCell requires={r.contributions.requires} />
              </div>
            ) : (
              <Contributions c={r.contributions} league={league} />
            )}
          </div>
          {r.grid ? <DistributionChart grid={r.grid} line={h?.threshold ?? null} label={catLabel.toLowerCase()} /> : null}
        </Section>

        <Section
          title="Season averages"
          summary={season?.avg != null ? `${fmt(season.avg)} in ${season.games} games` : "not published"}
        >
          {season ? (
            <div className="space-y-2">
              <p>
                {season.avg != null ? (
                  <>
                    <span className="font-mono text-ink">{fmt(season.avg)}</span> {catLabel.toLowerCase()} a game, over {season.games}{" "}
                    {season.games === 1 ? "game" : "games"} this season ({seasonText}).
                  </>
                ) : (
                  <>Played {season.games} {season.games === 1 ? "game" : "games"} this season ({seasonText}); no average published for this stat.</>
                )}
              </p>
              {hist.opportunity.length ? (
                <ul className="space-y-1">
                  {hist.opportunity.map((o) => {
                    const v = season.opportunity[o.key];
                    return v == null ? null : (
                      <li key={o.key}>
                        {o.label}: <span className="font-mono text-ink">{fmt(v)}</span> a game
                      </li>
                    );
                  })}
                </ul>
              ) : null}
              <p className="text-faint">
                Averages are what has happened. The projection above is what we expect in this game, against this opponent, with these minutes.
              </p>
            </div>
          ) : (
            <p>Season averages are not published on this board.</p>
          )}
        </Section>
      </div>

      <p className="text-xs text-faint">
        {r.supportNote ? `Behind the projection: ${r.supportNote}. ` : ""}
        Model Room projects players. It does not tell you what to bet.
      </p>
    </div>
  );
}
