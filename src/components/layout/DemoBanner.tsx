/** Persistent notice. Remove only when a live, validated provider is active. */
export function DemoBanner() {
  return (
    <div role="note" className="border-b border-edge/25 bg-edge/[0.08]">
      <p className="mx-auto max-w-7xl px-4 py-2 text-[0.82rem] leading-snug text-ink/85 sm:px-6">
        <span className="mr-2 inline-block rounded-sm bg-edge px-1.5 py-px font-display text-[0.8rem] font-700 text-navy-950">
          Demo
        </span>
        Teams, players and numbers on this site are fictional. Model Room&rsquo;s projection engines are not live yet.
      </p>
    </div>
  );
}
