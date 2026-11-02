import Link from "next/link";
import { addDays, longDate } from "@/lib/dates";
import { AutoSubmit } from "@/components/props/AutoSubmit";

/**
 * Previous / next game day, Today, Yesterday and a calendar. `date` null = the upcoming view.
 * `dates` are past days that have games (from the results history).
 */
export function DateNav({ base, params = {}, date, dates, today }: { base: string; params?: Record<string, string>; date: string | null; dates: string[]; today: string }) {
  const link = (d: string | null) => {
    const p = new URLSearchParams(params);
    if (d) p.set("date", d);
    const q = p.toString();
    return q ? `${base}?${q}` : base;
  };
  const current = date ?? today;
  const prev = [...dates].reverse().find((d) => d < current) ?? null;
  const next = date ? dates.find((d) => d > date && d < today) ?? null : null;
  const btn = "rounded-md border border-navy-700 bg-navy-900 px-3 py-1.5 text-sm text-ink hover:border-navy-600";
  const on = "rounded-md border border-model bg-model px-3 py-1.5 text-sm font-600 text-navy-950";
  const yesterday = addDays(today, -1);
  return (
    <div className="flex flex-wrap items-center gap-2">
      {prev ? <Link href={link(prev)} className={btn} aria-label="Previous game day">←</Link> : <span className={`${btn} opacity-40`} aria-hidden="true">←</span>}
      <Link href={link(null)} className={date ? btn : on}>Today</Link>
      <Link href={link(yesterday)} className={date === yesterday ? on : btn}>Yesterday</Link>
      {date ? (next ? <Link href={link(next)} className={btn} aria-label="Next game day">→</Link> : <Link href={link(null)} className={btn} aria-label="Back to upcoming">→</Link>) : null}
      <form action={base} className="flex items-center gap-2">
        {Object.entries(params).map(([k, v]) => <input key={k} type="hidden" name={k} value={v} />)}
        <label className="sr-only" htmlFor={`date-${base}`}>Pick a date</label>
        <input
          id={`date-${base}`}
          type="date"
          name="date"
          defaultValue={date ?? today}
          min={dates[0]}
          max={today}
          className="rounded-md border border-navy-700 bg-navy-900 px-2 py-1.5 font-mono text-sm text-ink"
        />
        <button type="submit" className={btn}>Go</button>
        <AutoSubmit inputs />
      </form>
      <span className="text-sm text-mute">{date ? longDate(date) : "Upcoming games"}</span>
    </div>
  );
}
