/** Model Room mark: market bar (white), model bar (blue), and the gap between them (orange). */
export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="var(--mr-soft)" stroke="var(--mr-line)" />
      <rect x="7" y="9" width="12" height="4" rx="2" fill="var(--mr-market)" />
      <rect x="7" y="19" width="18" height="4" rx="2" fill="var(--mr-model)" />
      <rect x="19" y="14.5" width="6" height="3" rx="1.5" fill="var(--mr-edge)" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      <span className="font-display text-[1.4rem] font-700 leading-none tracking-tight text-ink">
        Model Room
      </span>
    </span>
  );
}
