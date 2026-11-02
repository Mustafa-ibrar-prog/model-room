import { formatPct } from "@/lib/format";
import { getLeagueBoard } from "@/server/data";
import { getViewer } from "@/server/viewer";
import type { League } from "@/types/domain";
import { Panel, Unavailable } from "@/components/ui/primitives";

/** Backtest and live tracking summary. Shown to everyone: it's how the model is judged. */
export async function ModelPerformance({ league, compact = false }: { league: League; compact?: boolean }) {
  const viewer = await getViewer();
  const board = await getLeagueBoard(league, viewer.tier);
  if (!board.ok) return <Unavailable title="Model performance unavailable" body={board.reason} />;
  const { backtest, seasonToDate, ledger } = board.performance;

  return (
    <Panel className="p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-xl font-600 text-ink">{league.toUpperCase()} model {board.model.version}</h3>
        <span className="text-sm text-edge">{board.model.status.startsWith("provisional") ? "Provisional" : board.model.status}</span>
      </div>

      {backtest ? (
        <>
          <p className="mt-1 text-sm text-mute">
            Held-out test, seasons {backtest.testSeasons[0]}–{backtest.testSeasons[backtest.testSeasons.length - 1]} ({backtest.games.toLocaleString()} games), never used for tuning.
          </p>
          <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Margin error (avg)" value={`${backtest.marginMae.toFixed(2)} pts`} />
            <Stat label="Total error (avg)" value={`${backtest.totalMae.toFixed(2)} pts`} />
            <Stat label="Winner picked" value={formatPct(backtest.winnerCorrect, 1)} />
            <Stat label="Brier score" value={backtest.brier.toFixed(3)} hint="Lower is better; 0.25 = coin flip" />
          </dl>
          {!compact && (
            <table className="mt-5 w-full text-sm">
              <caption className="pb-2 text-left text-faint">Same test games, compared with simple baselines and the market</caption>
              <thead>
                <tr className="text-faint">
                  <th scope="col" className="py-1.5 text-left font-500">Method</th>
                  <th scope="col" className="py-1.5 text-right font-500">Margin error</th>
                  <th scope="col" className="py-1.5 text-right font-500">Total error</th>
                </tr>
              </thead>
              <tbody className="text-ink/90">
                <tr className="border-t border-navy-700/70">
                  <td className="py-1.5 text-model">Model Room</td>
                  <td className="py-1.5 text-right">{backtest.marginMae.toFixed(2)}</td>
                  <td className="py-1.5 text-right">{backtest.totalMae.toFixed(2)}</td>
                </tr>
                {backtest.marketMarginMae != null && (
                  <tr className="border-t border-navy-700/70">
                    <td className="py-1.5 text-market">Market line</td>
                    <td className="py-1.5 text-right">{backtest.marketMarginMae.toFixed(2)}</td>
                    <td className="py-1.5 text-right">{backtest.marketTotalMae?.toFixed(2) ?? "–"}</td>
                  </tr>
                )}
                {backtest.baselines.map((b) => (
                  <tr key={b.label} className="border-t border-navy-700/70">
                    <td className="py-1.5 text-mute">{b.label}</td>
                    <td className="py-1.5 text-right">{b.marginMae?.toFixed(2) ?? "–"}</td>
                    <td className="py-1.5 text-right">{b.totalMae?.toFixed(2) ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!compact && backtest.marketMarginMae == null && (
            <p className="mt-3 text-sm text-faint">No historical market lines are connected for this league, so the model hasn&rsquo;t been compared with the market.</p>
          )}
        </>
      ) : (
        <p className="mt-2 text-sm text-mute">No backtest report yet. Run the league&rsquo;s backtest command.</p>
      )}

      <div className="mt-5 grid gap-4 border-t border-navy-700 pt-4 sm:grid-cols-2">
        <div>
          <h4 className="text-sm font-600 text-ink">This season so far</h4>
          {seasonToDate ? (
            <p className="mt-1 text-sm text-mute">
              {seasonToDate.games} games: margin error {seasonToDate.marginMae.toFixed(2)}, total error {seasonToDate.totalMae.toFixed(2)}, winner {formatPct(seasonToDate.winnerCorrect)}.
            </p>
          ) : (
            <p className="mt-1 text-sm text-mute">No finished games yet.</p>
          )}
        </div>
        <div>
          <h4 className="text-sm font-600 text-ink">Stored pre-game predictions</h4>
          <p className="mt-1 text-sm text-mute">
            {ledger.tracked} stored, {ledger.graded} graded.
            {ledger.versions.map((v) => ` Version ${v.version}: margin error ${v.marginMae.toFixed(2)} over ${v.games} games.`).join("")}
          </p>
        </div>
      </div>
      <p className="mt-4 text-xs text-faint">Past accuracy doesn&rsquo;t guarantee future results. No claim is made that the model beats the market.</p>
    </Panel>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs text-mute">{label}</dt>
      <dd className="mt-0.5 font-display text-2xl font-700 text-ink">{value}</dd>
    </div>
  );
}
