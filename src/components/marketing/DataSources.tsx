import { Section } from "@/components/ui/primitives";

const SOURCES = [
  { name: "Schedules and results", use: "Game times, venues and final scores for ratings and backtests." },
  { name: "Betting lines", use: "Opening and current spreads, totals and prop lines from a licensed odds feed." },
  { name: "Official injury reports", use: "League-published player status, refreshed through game day." },
  { name: "Play-by-play and box scores", use: "Possession-level data behind offensive, defensive and pace ratings." },
  { name: "Rest and travel", use: "Days of rest, back-to-backs and distance traveled, derived from the schedule." },
];

export function DataSources() {
  return (
    <Section
      id="data-sources"
      title="Data sources"
      intro="What the model will run on. None of these feeds are connected yet. Each one will be listed here with its provider and refresh time once it is live."
    >
      <div className="overflow-hidden rounded-xl border border-navy-700">
        <table className="w-full border-collapse text-[0.95rem]">
          <caption className="sr-only">Planned data sources and their status.</caption>
          <thead className="bg-navy-850">
            <tr>
              <th scope="col" className="px-4 py-2.5 text-left text-[0.78rem] font-500 text-faint">Source</th>
              <th scope="col" className="hidden px-4 py-2.5 text-left text-[0.78rem] font-500 text-faint sm:table-cell">Used for</th>
              <th scope="col" className="px-4 py-2.5 text-right text-[0.78rem] font-500 text-faint">Status</th>
            </tr>
          </thead>
          <tbody className="bg-navy-900">
            {SOURCES.map((s) => (
              <tr key={s.name} className="border-t border-navy-700/70 align-top">
                <td className="px-4 py-3.5">
                  <div className="font-600 text-ink">{s.name}</div>
                  <div className="mt-1 text-sm text-mute sm:hidden">{s.use}</div>
                </td>
                <td className="hidden px-4 py-3.5 text-mute sm:table-cell">{s.use}</td>
                <td className="px-4 py-3.5 text-right">
                  <span className="whitespace-nowrap rounded-md bg-navy-800 px-2 py-0.5 text-sm text-mute">Not connected</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
