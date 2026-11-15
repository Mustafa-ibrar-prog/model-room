import Link from "next/link";

export type PerfTab = "nba-props" | "nfl-props" | "nba" | "nfl" | "stats";

const TABS: { key: PerfTab; href: string; label: string }[] = [
  { key: "nba-props", href: "/performance?tab=nba-props", label: "NBA Props" },
  { key: "nfl-props", href: "/performance?tab=nfl-props", label: "NFL Props" },
  { key: "nba", href: "/performance?tab=nba", label: "NBA" },
  { key: "nfl", href: "/performance?tab=nfl", label: "NFL" },
];

/** Performance: one results tab per sports section, and the technical record off to the side. */
export function PerformanceTabs({ active }: { active: PerfTab }) {
  const cls = (on: boolean) => `shrink-0 rounded-full px-4 py-2 text-sm ${on ? "bg-ink font-600 text-navy-950" : "border border-navy-700 font-500 text-mute hover:border-navy-600 hover:text-ink"}`;
  return (
    <nav aria-label="Performance" className="mx-auto mb-6 flex w-full max-w-7xl items-center gap-2 overflow-x-auto px-4 pb-1 sm:px-6">
      {TABS.map((t) => (
        <Link key={t.key} href={t.href} aria-current={active === t.key ? "page" : undefined} className={cls(active === t.key)}>
          {t.label}
        </Link>
      ))}
      <span className="mx-1 h-5 w-px shrink-0 bg-navy-700" aria-hidden="true" />
      <Link href="/performance/stats" aria-current={active === "stats" ? "page" : undefined} className={cls(active === "stats")}>
        Stats for Nerds
      </Link>
    </nav>
  );
}
