import { formatPct } from "@/lib/format";
import { providerName } from "@/lib/providers";
import type { PropLineView } from "@/types/props";

export const PROVIDERS = ["polymarket_us", "kalshi"] as const;
const VARIANT: Record<string, string> = { espn_ppr: "ESPN", sleeper_ppr: "Sleeper" };

export const fmt = (n: number) => (Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(1));
export const cents = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}`);

export function lineLabel(l: Pick<PropLineView, "op" | "threshold" | "variant">): string {
  const n = Number.isInteger(l.threshold) ? l.threshold.toFixed(0) : l.threshold.toFixed(1);
  return `${l.op === ">=" ? `${n}+` : `Over ${n}`}${l.variant ? ` ${VARIANT[l.variant] ?? l.variant}` : ""}`;
}

type Quote = PropLineView["quotes"][number];

/** The quote to show for each exchange on this line: its usable one if any, else its latest (flagged). */
export function quoteBy(l: PropLineView): Partial<Record<(typeof PROVIDERS)[number], Quote>> {
  const out: Partial<Record<(typeof PROVIDERS)[number], Quote>> = {};
  for (const p of PROVIDERS) {
    const qs = l.quotes.filter((q) => q.provider === p);
    if (!qs.length) continue;
    out[p] = qs.find((q) => q.usable) ?? [...qs].sort((a, b) => b.capturedAt.localeCompare(a.capturedAt))[0];
  }
  return out;
}

export function age(iso: string, now: number): string {
  const m = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

const FLAG: Record<string, string> = { stale: "Stale", thin: "Thin", "thin at ask": "Thin", "one-sided": "One-sided" };
export const flagText = (flags: string[]) => [...new Set(flags.map((f) => FLAG[f] ?? f))].join(", ");

/**
 * The signature mark: one 0–100% track with the model (blue) and the market (white) on it; the stretch
 * between them is orange when it's an edge after fees, gray otherwise. No market: the model tick alone.
 */
export function GapBar({ model, market, edge, className = "" }: { model: number; market: number | null; edge: boolean; className?: string }) {
  const lo = market == null ? model : Math.min(model, market);
  const hi = market == null ? model : Math.max(model, market);
  return (
    <div className={`relative h-1.5 rounded-full bg-navy-700 ${className}`} aria-hidden="true">
      {market != null ? (
        <div className={`absolute inset-y-0 rounded-full ${edge ? "bg-edge" : "bg-navy-600"}`} style={{ left: `${lo * 100}%`, width: `${Math.max((hi - lo) * 100, 0.8)}%` }} />
      ) : null}
      {market != null ? <div className="absolute -top-[3px] h-3 w-[3px] -translate-x-1/2 rounded bg-market" style={{ left: `${market * 100}%` }} /> : null}
      <div className="absolute -top-[3px] h-3 w-[3px] -translate-x-1/2 rounded bg-model" style={{ left: `${model * 100}%` }} />
    </div>
  );
}

export function EdgeTag({ l, compact = false }: { l: PropLineView; compact?: boolean }) {
  if (!l.edge) return null;
  const strong = l.edge.grade === "strong";
  return (
    <span
      title={`${strong ? "Strong edge" : `Lean, not strong: ${l.edge.reasons.join("; ")}`}. Buy ${l.edge.side === "yes" ? "Yes" : "No"} at ${cents(l.edge.price)}¢ on ${providerName(l.edge.provider)}; expected value after the fee.`}
      className={`whitespace-nowrap rounded px-1 font-mono ${compact ? "text-[0.62rem]" : "text-xs py-0.5"} ${strong ? "bg-edge font-600 text-navy-950" : "border border-edge/70 text-edge"}`}
    >
      {strong ? "Edge" : "Lean"} {l.edge.side === "yes" ? "Yes" : "No"} +{(l.edge.ev * 100).toFixed(1)}¢
    </span>
  );
}

export const pct = formatPct;
