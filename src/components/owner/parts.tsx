/**
 * Shared pieces for the owner dashboard. Two kinds of figure, never mixed:
 *   <Observed>  market data as collected (white): a book's line, price, implied probability, movement.
 *   <Estimated> Model Room output (blue): a probability or projection, always with its model version.
 */
import type { ReactNode } from "react";
import { formatTimestamp } from "@/lib/format";

export const Observed = ({ children, title }: { children: ReactNode; title?: string }) => <span className="font-mono text-market" title={title}>{children}</span>;
export const Estimated = ({ children, title }: { children: ReactNode; title?: string }) => <span className="font-mono text-model" title={title}>{children}</span>;

export function Legend() {
  return (
    <p className="flex flex-wrap gap-x-4 gap-y-1 text-[0.72rem] text-mute">
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-market" />Observed market data (as collected)</span>
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-model" />Model Room estimate (version shown)</span>
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-faint" />Insufficient sample or not available</span>
    </p>
  );
}

export function Stat({ label, value, sub, tone = "ink" }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ink" | "market" | "model" | "edge" | "faint" }) {
  const c = { ink: "text-ink", market: "text-market", model: "text-model", edge: "text-edge", faint: "text-faint" }[tone];
  return (
    <div className="min-w-0 rounded-lg bg-navy-900 px-3.5 py-3">
      <div className="text-[0.72rem] text-faint">{label}</div>
      <div className={`font-mono text-xl leading-tight ${c}`}>{value}</div>
      {sub ? <div className="mt-0.5 text-[0.7rem] text-mute">{sub}</div> : null}
    </div>
  );
}

export function Block({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <div>
        <h3 className="font-display text-lg font-600 text-ink">{title}</h3>
        {intro ? <p className="max-w-3xl text-xs leading-relaxed text-mute">{intro}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return <p className={`rounded-md border px-3 py-2 text-xs leading-relaxed ${tone === "warn" ? "border-edge/50 text-ink" : "border-navy-700 text-mute"}`}>{children}</p>;
}

export function UnavailableState({ what, reason }: { what: string; reason: "not_configured" | "unreachable" | "empty" }) {
  const text = {
    not_configured: "The read-only database connection (MODELROOM_OWNER_DB_URL) is not configured on this deployment, so this section has no data. Nothing is estimated or filled in.",
    unreachable: "The read-only database could not be reached just now. Nothing is estimated or filled in; reload to try again.",
    empty: "No records yet.",
  }[reason];
  return (
    <div className="rounded-lg border border-dashed border-navy-600 px-4 py-5 text-sm">
      <div className="font-600 text-ink">{what}: unavailable</div>
      <p className="mt-1 text-xs text-mute">{text}</p>
    </div>
  );
}

export const Insufficient = ({ note }: { note?: string }) => <span className="text-faint" title={note}>insufficient sample</span>;

export const ts = (iso: string | null | undefined) => (iso ? formatTimestamp(iso) : "–");

export function ago(iso: string | null | undefined, now: number): string {
  if (!iso) return "never";
  const h = (now - Date.parse(iso)) / 3.6e6;
  if (h < 1) return `${Math.max(0, Math.round(h * 60))} min ago`;
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export const n3 = (x: number | null | undefined) => (x == null ? "–" : x.toFixed(3));
export const pct = (x: number | null | undefined, d = 1) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
export const signed = (x: number | null | undefined, d = 2) => (x == null ? "–" : `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(d)}`);

/** Reliability diagram: each bin's average predicted probability against how often it happened. Bins under `minN` are hollow and grey. */
export function Reliability({ bins, minN, label }: { bins: { bin: string; n: number; predicted: number | null; actual: number | null }[]; minN: number; label: string }) {
  const W = 260, H = 200, L = 34, B = 26, T = 8, R = 8;
  const X = (p: number) => L + p * (W - L - R);
  const Y = (p: number) => H - B - p * (H - B - T);
  const pts = bins.filter((b) => b.predicted != null && b.actual != null);
  const maxN = Math.max(1, ...pts.map((b) => b.n));
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full max-w-[18rem]" role="img" aria-label={`Calibration of ${label}: predicted against observed`}>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line x1={X(0)} x2={X(1)} y1={Y(g)} y2={Y(g)} stroke="var(--color-navy-700)" strokeWidth="1" />
            <text x={L - 6} y={Y(g) + 3} textAnchor="end" fontSize="9" fill="var(--color-faint)">{Math.round(g * 100)}</text>
            <text x={X(g)} y={H - 10} textAnchor="middle" fontSize="9" fill="var(--color-faint)">{Math.round(g * 100)}</text>
          </g>
        ))}
        <line x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(1)} stroke="var(--color-mute)" strokeWidth="1" strokeDasharray="3 3" />
        {pts.map((b) => {
          const ok = b.n >= minN;
          const r = 2.5 + 4 * Math.sqrt(b.n / maxN);
          return <circle key={b.bin} cx={X(b.predicted!)} cy={Y(b.actual!)} r={r} fill={ok ? "var(--color-model)" : "none"} stroke={ok ? "var(--color-model)" : "var(--color-faint)"} strokeWidth="1.2"><title>{`${b.bin}: predicted ${(b.predicted! * 100).toFixed(1)}%, happened ${(b.actual! * 100).toFixed(1)}% (n ${b.n})`}</title></circle>;
        })}
      </svg>
      <figcaption className="text-[0.68rem] text-faint">Predicted % (across) vs observed % (up). Dashed line = perfect calibration. Hollow = under {minN} rows.</figcaption>
    </figure>
  );
}

export function Table({ head, children, className = "" }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-navy-700">
      <table className={`w-full text-xs ${className}`}>
        <thead className="bg-navy-900 text-faint">
          <tr>{head.map((h, i) => <th key={i} className={`whitespace-nowrap px-2.5 py-2 font-500 ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-navy-700/70">{children}</tbody>
      </table>
    </div>
  );
}
