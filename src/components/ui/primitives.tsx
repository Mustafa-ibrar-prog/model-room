import Link from "next/link";
import type { ReactNode } from "react";
import { tierName } from "@/config/tiers";
import { isLocked, type Gate, type TierId } from "@/types/domain";

export function PageHeader({ title, intro, children }: { title: string; intro: string; children?: ReactNode }) {
  return (
    <div className="mx-auto max-w-7xl px-4 pb-6 pt-10 sm:px-6 sm:pt-14">
      <h1 className="font-display text-4xl font-700 leading-none tracking-tight text-ink sm:text-5xl">{title}</h1>
      <p className="mt-3 max-w-2xl text-base leading-relaxed text-mute">{intro}</p>
      {children}
    </div>
  );
}

export function Section({ id, title, intro, children, action }: { id?: string; title: string; intro?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-7xl scroll-mt-24 px-4 py-10 sm:px-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-[1.9rem] font-700 leading-tight tracking-tight text-ink">{title}</h2>
          {intro && <p className="mt-1.5 max-w-2xl text-[0.95rem] leading-relaxed text-mute">{intro}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-navy-700 bg-navy-900 ${className}`}>{children}</div>;
}

/** Small "Demo data" stamp placed on every table caption. */
export function DemoStamp() {
  return (
    <span className="rounded-sm border border-edge/40 px-1.5 py-px font-display text-[0.75rem] font-600 text-edge">
      Demo data
    </span>
  );
}

export function LockIcon({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="currentColor" aria-hidden="true">
      <path d="M5 7V5a3 3 0 1 1 6 0v2h.5A1.5 1.5 0 0 1 13 8.5v5A1.5 1.5 0 0 1 11.5 15h-7A1.5 1.5 0 0 1 3 13.5v-5A1.5 1.5 0 0 1 4.5 7H5Zm1.5 0h3V5a1.5 1.5 0 1 0-3 0v2Z" />
    </svg>
  );
}

/** Table cell content for a value the viewer's plan does not include. */
export function LockedCell({ requires }: { requires: TierId }) {
  return (
    <Link
      href="/pricing"
      className="inline-flex items-center gap-1 rounded-sm text-[0.8rem] font-500 text-faint hover:text-ink"
      title={`Included with ${tierName(requires)}`}
    >
      <LockIcon />
      {tierName(requires)}
    </Link>
  );
}

/** Render a gated value, or the lock cell if it is locked. */
export function Gated<T>({ value, children }: { value: Gate<T>; children: (v: T) => ReactNode }) {
  if (isLocked(value)) return <LockedCell requires={value.requires} />;
  return <>{children(value)}</>;
}

/** Full-width notice for a whole feature the plan does not include. */
export function LockedPanel({ requires, title, body }: { requires: TierId; title: string; body: string }) {
  return (
    <Panel className="relative min-h-[19rem] overflow-hidden">
      <div aria-hidden="true" className="space-y-3 p-5 opacity-40 blur-[1px]">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="flex gap-4">
            <div className="h-4 w-40 rounded bg-navy-700" />
            <div className="h-4 w-16 rounded bg-navy-700" />
            <div className="h-4 w-16 rounded bg-navy-800" />
            <div className="h-4 flex-1 rounded bg-navy-800" />
          </div>
        ))}
      </div>
      <div className="absolute inset-0 flex items-center justify-center bg-navy-950/55 p-6">
        <div className="max-w-md text-center">
          <LockIcon className="mx-auto h-6 w-6 text-edge" />
          <h3 className="mt-3 font-display text-2xl font-700 text-ink">{title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-mute">{body}</p>
          <Link
            href="/pricing"
            className="mt-4 inline-block rounded-full bg-model px-4 py-2 text-sm font-600 text-navy-950 hover:bg-model/90"
          >
            Compare plans
          </Link>
          <p className="mt-2 text-xs text-faint">Included with {tierName(requires)} and above.</p>
        </div>
      </div>
    </Panel>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <Panel className="p-5" >
      <div className="animate-pulse space-y-3" aria-label="Loading">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-6 rounded bg-navy-800" />
        ))}
      </div>
    </Panel>
  );
}

export function Th({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <th scope="col" className={`whitespace-nowrap px-3 py-2.5 text-left text-[0.78rem] font-500 text-faint ${className}`}>
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`whitespace-nowrap px-3 py-3 align-middle ${className}`}>{children}</td>;
}
