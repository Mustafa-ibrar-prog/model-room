import Link from "next/link";
import { addDays, longDate } from "@/lib/dates";
import { AutoSubmit } from "@/components/props/AutoSubmit";

/**
 * Day navigation: ‹ / › step through days that have games; Yesterday / Today / Tomorrow; All upcoming;
 * and a calendar. `date` null = every upcoming game. Past days come from the results history
 * (`dates`), coming days from the schedule (`upcoming`).
 */
export function DateNav({
  base,
  params = {},
  date,
  dates,
  upcoming = [],
  today,
}: {
  base: string;
  params?: Record<string, string>;
  date: string | null;
  dates: string[];
  upcoming?: string[];
  today: string;
}) {
  const link = (d: string | null) => {
    const p = new URLSearchParams(params);
    if (d) p.set("date", d);
    const q = p.toString();
    return q ? `${base}?${q}` : base;
  };
  const days = [...new Set([...dates, ...upcoming])].sort();
  const ref = date ?? today;
  const prev = [...days].reverse().find((d) => d < ref) ?? null;
  const next = days.find((d) => d > ref) ?? null;
  const yesterday = addDays(today, -1);
  const tomorrow = addDays(today, 1);
  const chip = (on: boolean) => `whitespace-nowrap rounded-full px-3 py-1.5 text-sm ${on ? "bg-ink font-600 text-navy-950" : "bg-navy-850 text-mute hover:text-ink"}`;
  const arrow = "rounded-full bg-navy-850 px-2.5 py-1.5 text-sm text-mute hover:text-ink";
  const max = upcoming.length ? upcoming[upcoming.length - 1] : today;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {prev ? <Link href={link(prev)} className={arrow} aria-label={`Previous game day, ${longDate(prev)}`}>‹</Link> : <span className={`${arrow} opacity-40`} aria-hidden="true">‹</span>}
      <Link href={link(yesterday)} className={chip(date === yesterday)}><span className="sm:hidden">Yest.</span><span className="hidden sm:inline">Yesterday</span></Link>
      <Link href={link(today)} className={chip(date === today)}>Today</Link>
      <Link href={link(tomorrow)} className={chip(date === tomorrow)}>Tomorrow</Link>
      <Link href={link(null)} className={chip(date === null)}><span className="sm:hidden">All</span><span className="hidden sm:inline">All upcoming</span></Link>
      {next ? <Link href={link(next)} className={arrow} aria-label={`Next game day, ${longDate(next)}`}>›</Link> : <span className={`${arrow} opacity-40`} aria-hidden="true">›</span>}
      <form action={base} className="flex items-center gap-1.5">
        {Object.entries(params).map(([k, v]) => <input key={k} type="hidden" name={k} value={v} />)}
        <label className="sr-only" htmlFor={`date-${base}`}>Pick a date</label>
        <input id={`date-${base}`} type="date" name="date" defaultValue={date ?? today} min={days[0]} max={max}
          className="w-[9.5rem] rounded-full border border-navy-700 bg-navy-900 px-3 py-1 font-mono text-sm text-ink" />
        <noscript><button type="submit" className={arrow}>Go</button></noscript>
        <AutoSubmit inputs />
      </form>
      <span className="ml-1 hidden text-sm text-mute sm:inline">{date ? longDate(date) : "All upcoming games"}</span>
    </div>
  );
}
