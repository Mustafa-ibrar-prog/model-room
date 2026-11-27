import Link from "next/link";
import { TeamBadge } from "@/components/ui/TeamBadge";
import { formatPct } from "@/lib/format";
import type { ExplorerRow } from "@/server/data/explorer";
import type { League } from "@/types/domain";

/** "4:32 PM" Pacific: when the sportsbook last updated the line. */
export const bookTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" }) + " PT" : "time unknown";
import { headlineFor, historyCaveat, listedText, playerSub, projText } from "./simple";

/**
 * One player, one stat, seven things: who, which stat, the market line if a market has quoted one,
 * our projection, the chance of clearing a stated threshold, the chance of falling short, and a way in.
 * No tables, no statistics dump, and nothing invented when a number does not exist.
 */
export function PlayerCard({ league, r, catLabel, href, listed = null }: { league: League; r: ExplorerRow; catLabel: string; href: string; listed?: "out" | "doubtful" | "questionable" | null }) {
  const h = headlineFor(r);
  const caveat = listed ? listedText(listed) : historyCaveat(r);
  const pct = h ? Math.round(h.prob * 100) : null;

  return (
    <article className="rounded-xl bg-navy-900 transition-colors hover:bg-navy-850">
      {/* phone: name and the answer on one line, the rest underneath */}
      <Link href={href} scroll={false} className="block p-4 sm:hidden" aria-label={`${r.name}, ${catLabel.toLowerCase()}: see why`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <TeamBadge league={league} abbr={r.team} size="sm" />
            <div className="min-w-0">
              <p className="truncate text-[1.05rem] font-600 text-ink">{r.name}</p>
              <p className="truncate text-[0.8rem] text-mute">{playerSub(r)}</p>
            </div>
          </div>
          {h && pct !== null ? (
            <div className="shrink-0 text-right">
              <p className="font-display text-4xl font-700 leading-none text-ink">{pct}%</p>
              <p className="mt-0.5 text-xs text-mute">chance of {h.thresholdText}</p>
            </div>
          ) : null}
        </div>
        {h && pct !== null ? (
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-navy-600" aria-hidden="true">
            <div className="h-full bg-model" style={{ width: `${pct}%` }} />
          </div>
        ) : null}
        <p className="mt-2 text-[0.8rem] text-faint">
          {catLabel} &middot; we project <span className="font-600 text-model">{projText(r)}</span> &middot;{" "}
          {h?.fromMarket ? <>line <span className="text-market">{h.threshold}</span></> : r.lineStatus ? `sportsbook line ${r.lineStatus.label.toLowerCase()}` : "no sportsbook line"}
        </p>
        {caveat ? <p className="mt-1 text-xs text-edge">{caveat}</p> : null}
        <p className="mt-1.5 text-[0.8rem] font-500 text-model">See why</p>
      </Link>

      <div className="hidden flex-wrap items-center gap-x-6 gap-y-4 p-5 sm:flex">
        {/* who */}
        <TeamBadge league={league} abbr={r.team} size="sm" />
        <div className="min-w-0 flex-[1_1_10rem]">
          <Link href={href} scroll={false} className="block truncate text-lg font-600 text-ink hover:text-model">
            {r.name}
          </Link>
          <p className="truncate text-sm text-mute">{playerSub(r)}</p>
        </div>

        {/* which stat */}
        <p className="flex-[0_0_5.5rem] text-sm text-faint">{catLabel}</p>

        {/* the market's number, when a market has one */}
        <div className="flex-[0_0_6.5rem]">
          <p className="text-xs text-faint">Sportsbook line</p>
          {h?.fromMarket ? (
            <>
              <p className="font-display text-2xl font-600 leading-none text-market">{h.threshold}</p>
              {h.book ? <p className="mt-1 text-[0.7rem] leading-tight text-faint">{h.book.books.length === 1 ? h.book.books[0].title : `${h.book.books.length} books`} · {bookTime(h.book.lastUpdate)}</p> : null}
            </>
          ) : r.lineStatus ? (
            <>
              <p className={`text-sm font-600 ${r.lineStatus.state === "pending" ? "text-pending" : "text-faint"}`}>{r.lineStatus.label}</p>
              <p className="mt-1 text-[0.7rem] leading-tight text-faint">{r.lineStatus.reason}</p>
            </>
          ) : (
            <p className="text-sm text-faint">none</p>
          )}
        </div>

        {/* ours */}
        <div className="flex-[0_0_6rem]">
          <p className="text-xs text-faint">We project</p>
          <p className="font-display text-3xl font-600 leading-none text-model">{projText(r)}</p>
        </div>

        {/* the five-second answer */}
        <div className="flex-[1_1_14rem]">
          {h && pct !== null ? (
            <>
              <p className="text-[0.8rem] text-mute">Chance of {h.thresholdText}</p>
              <p className="flex items-baseline gap-2.5">
                <span className="font-display text-4xl font-700 leading-none text-ink">{pct}%</span>
                <span className="text-sm text-mute">{h.belowText} {formatPct(h.belowProb)}</span>
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-navy-600" aria-hidden="true">
                <div className="h-full bg-model" style={{ width: `${pct}%` }} />
              </div>
              {caveat ? <p className="mt-1.5 text-xs text-edge">{caveat}</p> : null}
            </>
          ) : (
            <p className="text-sm text-faint">No projection published for this stat</p>
          )}
        </div>

        <Link
          href={href}
          scroll={false}
          className="shrink-0 rounded-full border border-navy-700 px-4 py-2 text-sm font-500 text-model hover:border-model"
          aria-label={`Why we project ${projText(r)} ${catLabel.toLowerCase()} for ${r.name}`}
        >
          See why
        </Link>
      </div>
    </article>
  );
}
