import { teamColor, teamInk } from "@/config/teams";
import type { League } from "@/types/domain";

export function TeamBadge({ league, abbr, size = "md" }: { league: League; abbr: string; size?: "sm" | "md" }) {
  const bg = teamColor(league, abbr);
  const dims = size === "sm" ? "h-6 min-w-6 text-[0.65rem]" : "h-8 min-w-8 text-xs";
  return (
    <span
      aria-hidden="true"
      className={`inline-flex items-center justify-center rounded-md px-1 font-display font-700 tracking-wide ${dims}`}
      style={{ background: bg, color: teamInk(bg) }}
    >
      {abbr}
    </span>
  );
}
