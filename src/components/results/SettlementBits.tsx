import { formatNumber, formatPct, formatTimestamp } from "@/lib/format";
import { providerName } from "@/lib/providers";
import type { MarketResult, SettleStatus } from "@/types/marketResults";

const STATUS: Record<SettleStatus, { label: string; cls: string }> = {
  won: { label: "Correct", cls: "border-good/60 bg-good/10 text-good" },
  lost: { label: "Incorrect", cls: "border-danger/60 bg-danger/10 text-danger" },
  void: { label: "Void / refunded", cls: "border-navy-600 bg-navy-850 text-mute" },
  no_call: { label: "No call (50%)", cls: "border-navy-600 bg-navy-850 text-mute" },
  pending: { label: "Pending settlement", cls: "border-pending/60 bg-pending/10 text-pending" },
};

export function StatusChip({ status, compact = false }: { status: SettleStatus; compact?: boolean }) {
  const s = STATUS[status];
  return <span className={`whitespace-nowrap rounded border px-1.5 py-px font-mono ${compact ? "text-[0.62rem]" : "text-[0.7rem]"} ${s.cls}`}>{s.label}</span>;
}

export function StatusLegend() {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      {(["won", "lost", "void", "pending"] as const).map((s) => <StatusChip key={s} status={s} />)}
      <span className="text-faint">Graded only when the exchange officially settles the market, never when the game ends.</span>
    </div>
  );
}

const lineText = (r: MarketResult) => {
  const n = r.threshold == null ? "" : Number.isInteger(r.threshold) ? r.threshold.toFixed(0) : r.threshold.toFixed(1);
  if (r.market === "game_winner") return `${r.team} to win`;
  if (r.market === "game_spread") return `${r.team} wins by more than ${n}`;
  if (r.market === "game_total") return `Over ${n} total points`;
  return `${r.op === ">=" ? `${n}+` : `Over ${n}`} ${r.market_label.toLowerCase()}`;
};

export function resultTitle(r: MarketResult): string {
  return r.kind === "prop" ? `${r.player ?? "Player"}: ${lineText(r)}` : lineText(r);
}

function settledText(r: MarketResult): string {
  const s = r.settlement;
  if (!s) return "No settlement reported yet.";
  if (s.state !== "settled") return `Pending (${s.provider_status ?? "open"}${s.note ? `: ${s.note}` : ""}).`;
  const what = s.result === "yes" ? "Yes" : s.result === "no" ? "No" : `Void${s.note ? `, ${s.note}` : ""}`;
  return `Settled ${what}${s.settled_at ? ` at ${formatTimestamp(s.settled_at)}` : ""}${s.settled_at_source && s.settled_at_source !== "settlement_ts" ? ` (${s.settled_at_source})` : ""}.`;
}

/** One graded prediction: summary line, and on open the original projection, the market then, and the settlement. */
export function ResultRow({ r }: { r: MarketResult }) {
  const diff = r.market_implied != null ? Math.round((r.model_prob - r.market_implied) * 100) : null;
  return (
    <li>
      <details className="group rounded-md border border-navy-700 bg-navy-900">
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 [&::-webkit-details-marker]:hidden">
          <StatusChip status={r.status} />
          <span className="min-w-0 flex-1 truncate text-sm text-ink">{resultTitle(r)}</span>
          <span className="font-mono text-xs text-model" title="Model probability">{formatPct(r.model_prob)}</span>
          <span className="font-mono text-xs text-market" title="Market-implied probability when the model ran">{r.market_implied != null ? formatPct(r.market_implied) : "–"}</span>
          <span className="font-mono text-[0.68rem] text-faint">{providerName(r.provider)}</span>
        </summary>
        <dl className="grid gap-x-4 gap-y-1 border-t border-navy-700/70 px-3 py-2 text-xs sm:grid-cols-2">
          <div className="sm:col-span-2 text-faint">{r.game_date} · market {r.market_id}</div>
          <div><dt className="inline text-model">Model Room: </dt><dd className="inline text-ink">
            {formatPct(r.model_prob, 1)} Yes ({r.model_call ? `called ${r.model_call === "yes" ? "Yes" : "No"}` : "no call"})
            {r.projection?.mean != null ? `, projected ${formatNumber(r.projection.mean)}${r.projection.sd != null ? ` ± ${formatNumber(r.projection.sd)}` : ""}` : ""}
            {r.projection?.margin != null ? `, projected ${r.projection.home} by ${formatNumber(r.projection.margin)}, total ${formatNumber(r.projection.total ?? 0)}` : ""}
          </dd></div>
          <div><dt className="inline text-market">Market then: </dt><dd className="inline text-ink">
            {r.market_bid != null || r.market_ask != null ? `${r.market_bid != null ? Math.round(r.market_bid * 100) : "–"}/${r.market_ask != null ? Math.round(r.market_ask * 100) : "–"}¢, implied ${r.market_implied != null ? formatPct(r.market_implied, 1) : "–"}` : "no price recorded"}
            {diff != null ? ` (gap ${diff > 0 ? "+" : ""}${diff} pts)` : ""}
          </dd></div>
          <div><dt className="inline text-faint">Predicted: </dt><dd className="inline text-mute">{formatTimestamp(r.predicted_at)}, model {r.model_version}</dd></div>
          <div><dt className="inline text-faint">Settlement: </dt><dd className="inline text-mute">{settledText(r)}</dd></div>
          {r.actual?.stat != null ? <div><dt className="inline text-faint">Actual stat: </dt><dd className="inline text-mute">{formatNumber(r.actual.stat)} (context only; the grade is the settlement)</dd></div> : null}
          {r.actual?.home_score != null ? <div><dt className="inline text-faint">Final: </dt><dd className="inline text-mute">{r.actual.away} {r.actual.away_score}, {r.actual.home} {r.actual.home_score}</dd></div> : null}
          {r.edge ? (
            <div><dt className="inline text-edge">Model-implied +EV flag (unverified): </dt><dd className="inline text-mute">{r.edge.grade === "strong" ? "no data warnings" : "with data warnings"} on {r.edge.side === "yes" ? "Yes" : "No"}{r.edge.result ? `, ${r.edge.result === "won" ? "correct" : "incorrect"}` : ""}</dd></div>
          ) : null}
          {r.corrections.length ? (
            <div className="sm:col-span-2 text-pending">
              Settlement corrected: {r.corrections.map((c) => `${c.was ?? "?"} → ${c.result ?? "pending"} (${formatTimestamp(c.observed_at)})`).join("; ")}
            </div>
          ) : null}
        </dl>
      </details>
    </li>
  );
}
