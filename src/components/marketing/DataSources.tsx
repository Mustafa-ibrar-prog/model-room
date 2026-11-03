import { Section } from "@/components/ui/primitives";

type Status = "Connected" | "Optional" | "Not connected";

const SOURCES: { name: string; league: string; use: string; status: Status }[] = [
  { name: "nflverse schedules, results and lines", league: "NFL", use: "Game times, final scores, rest days, starting quarterbacks, and one published spread and total per game.", status: "Connected" },
  { name: "nflverse play-by-play", league: "NFL", use: "Every play's expected points added (EPA) and success, behind the offense and defense ratings.", status: "Connected" },
  { name: "nflverse injury reports", league: "NFL", use: "Game designations and practice participation.", status: "Connected" },
  { name: "hoopR schedules and box scores", league: "NBA", use: "Game times, final scores and the box-score counts behind possessions, pace and efficiency.", status: "Connected" },
  { name: "Land of Basketball results", league: "NBA", use: "Independent check that final scores match.", status: "Connected" },
  { name: "Sportsbook lines (The Odds API or manual entry)", league: "NBA, NFL", use: "Current spreads, totals and moneylines with sportsbook and timestamp.", status: "Optional" },
  { name: "NBA injury report", league: "NBA", use: "Player availability for injury adjustments.", status: "Not connected" },
];

const STYLE: Record<Status, string> = {
  Connected: "bg-model/15 text-model",
  Optional: "bg-market/15 text-market",
  "Not connected": "bg-navy-800 text-mute",
};

export function DataSources() {
  return (
    <Section
      id="data-sources"
      title="Data sources"
      intro="Public datasets only, collected within each site's rules. Official league sites are used for reference until their data is licensed."
    >
      <div className="overflow-hidden rounded-xl border border-navy-700">
        <table className="w-full border-collapse text-[0.95rem]">
          <caption className="sr-only">Data sources and their status.</caption>
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
                <td className="px-4 py-2.5 sm:py-3.5">
                  <div className="font-600 text-ink">{s.name}</div>
                  <div className="text-xs text-faint">{s.league}</div>
                  <div className="mt-1 line-clamp-2 text-xs text-mute sm:hidden">{s.use}</div>
                </td>
                <td className="hidden px-4 py-3.5 text-mute sm:table-cell">{s.use}</td>
                <td className="px-4 py-3.5 text-right">
                  <span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-sm ${STYLE[s.status]}`}>{s.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-faint">
        NFL data by nflverse (CC-BY 4.0). NBA data by hoopR / sportsdataverse, from ESPN.
      </p>
    </Section>
  );
}
