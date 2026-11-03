import Link from "next/link";
import { favoredLine, formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { longDate } from "@/lib/dates";
import { getHistoryDay } from "@/server/data/history";
import { getMarketResultsForDate } from "@/server/data/marketResults";
import { ResultRow } from "@/components/results/SettlementBits";
import { getViewer } from "@/server/viewer";
import { isLocked, type League } from "@/types/domain";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { LockedCell, Unavailable } from "@/components/ui/primitives";

/** A past date: final scores, and (Pro) what the model recorded before each game. */
export async function HistoryGames({ league, date }: { league: League; date: string }) {
  const viewer = await getViewer();
  const [h, settled] = await Promise.all([getHistoryDay(league, date, viewer.tier), getMarketResultsForDate(league, date, viewer.tier)]);
  const gameMarkets = isLocked(settled) ? [] : settled.filter((r) => r.kind === "game");
  if (!h.available || !h.games.length) {
    return <Unavailable title={`No ${league.toUpperCase()} games on ${longDate(date)}`} body="Pick another day with the arrows or the calendar." />;
  }
  const recorded = h.games.filter((g) => g.pregame).length;
  return (
    <div className="space-y-3">
      <p className="text-sm text-mute">
        {recorded
          ? `${recorded} of ${h.games.length} games have a projection recorded before kickoff.`
          : `No projection was recorded before these games. The record starts ${h.firstRecorded ?? "with the first model run"}; earlier dates show results only.`}
      </p>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {h.games.map((g) => {
          const pre = g.pregame && !isLocked(g.pregame) ? g.pregame : null;
          const res = g.result && !isLocked(g.result) ? g.result : null;
          return (
            <li key={g.game_id} className="rounded-lg border border-navy-700 bg-navy-900">
              <div className="flex items-center justify-between border-b border-navy-700/70 px-4 py-2 text-xs">
                <span className="font-mono uppercase tracking-wider text-faint">{g.final ? "Final" : g.status === "scheduled" ? "No result yet" : g.status}</span>
                {res?.winner_correct != null ? (
                  <span className={`font-mono ${res.winner_correct ? "text-good" : "text-danger"}`}>{res.winner_correct ? "Winner ✓" : "Winner ✗"}</span>
                ) : null}
              </div>
              <div className="space-y-2 px-4 py-3">
                {[{ t: g.away, s: g.final?.away, p: pre?.pred_away_score }, { t: g.home, s: g.final?.home, p: pre?.pred_home_score }].map(({ t, s, p }) => (
                  <div key={t} className="flex items-center gap-2.5">
                    <TeamBadge league={league} abbr={t} />
                    <span className="flex-1 font-display text-lg font-600 text-ink">{t}</span>
                    <span className="font-display text-2xl font-700 text-ink">{s ?? "–"}</span>
                    {p != null ? <span className="w-12 text-right font-mono text-sm text-model" title="Recorded projection">{formatNumber(p)}</span> : null}
                  </div>
                ))}
              </div>
              <div className="border-t border-navy-700/70 px-4 py-2.5 text-xs text-mute">
                {g.pregame && isLocked(g.pregame) ? (
                  <span className="flex items-center gap-2">Recorded projection: <LockedCell requires={g.pregame.requires} /></span>
                ) : pre ? (
                  <div className="space-y-0.5">
                    <div>
                      Projected {favoredLine(-pre.pred_margin, g.home, g.away).text}, total {formatNumber(pre.pred_total)}, {g.home} win {formatPct(pre.home_win_prob)}
                    </div>
                    {res ? <div>Off by {Math.abs(res.margin_error).toFixed(1)} on the margin, {Math.abs(res.total_error).toFixed(1)} on the total</div> : null}
                    <div className="text-faint">Recorded {formatTimestamp(pre.generated_at)}, model {pre.model_version}</div>
                  </div>
                ) : (
                  <span>No projection recorded before this game.</span>
                )}
                {gameMarkets.some((r) => r.game_id === g.game_id) ? (
                  <ul className="mt-2 space-y-1">{gameMarkets.filter((r) => r.game_id === g.game_id).map((r) => <ResultRow key={r.id} r={r} />)}</ul>
                ) : null}
                {g.final ? (
                  <Link href={`/props?sport=${league}&date=${date}&game=${encodeURIComponent(g.game_id)}`} className="mt-1 block font-600 text-model hover:underline">
                    Props results
                  </Link>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
