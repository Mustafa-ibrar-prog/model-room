import type { Metadata } from "next";
import { Suspense } from "react";
import { PricingTiers } from "@/components/marketing/PricingTiers";
import { authEnabled } from "@/lib/auth-config";
import { getViewer } from "@/server/viewer";
import { PageHeader, Section } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Pricing" };

type Row = { label: string; free: boolean | string; plus: boolean | string; pro: boolean | string };

const MATRIX: { group: string; rows: Row[] }[] = [
  {
    group: "Games",
    rows: [
      { label: "NFL and NBA schedules", free: true, plus: true, pro: true },
      { label: "Spread and total projections", free: "Basic", plus: "Full", pro: "Full" },
      { label: "Model vs sportsbook comparison", free: "First 2 games", plus: "Every game", pro: "Every game" },
      { label: "Projected scores", free: false, plus: true, pro: true },
      { label: "Line movement", free: false, plus: true, pro: true },
      { label: "Matchup breakdowns", free: false, plus: true, pro: true },
    ],
  },
  {
    group: "Players and injuries",
    rows: [
      { label: "Injury reports", free: "Basic", plus: true, pro: true },
      { label: "Injury adjustments to lines", free: false, plus: true, pro: true },
      { label: "Player prop projections", free: false, plus: true, pro: true },
      { label: "Advanced prop analysis", free: false, plus: false, pro: true },
    ],
  },
  {
    group: "Tools",
    rows: [
      { label: "Daily insights", free: true, plus: true, pro: true },
      { label: "Watchlists", free: false, plus: true, pro: true },
      { label: "Historical model data", free: false, plus: false, pro: true },
      { label: "Advanced analytics", free: false, plus: false, pro: true },
      { label: "Customizable alerts", free: false, plus: false, pro: true },
      { label: "Downloadable reports", free: false, plus: false, pro: true },
    ],
  },
];

function Cell({ v }: { v: boolean | string }) {
  if (typeof v === "string") return <span className="text-ink/90">{v}</span>;
  return v ? (
    <span className="text-model">
      <svg viewBox="0 0 16 16" className="ml-auto h-4 w-4 sm:mx-auto" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
        <path d="M3 8.5l3 3 7-7" />
      </svg>
      <span className="sr-only">Included</span>
    </span>
  ) : (
    <span className="text-faint">
      <span aria-hidden="true">–</span>
      <span className="sr-only">Not included</span>
    </span>
  );
}

async function Tiers() {
  const viewer = await getViewer();
  return <PricingTiers viewer={{ authOn: authEnabled(), signedIn: Boolean(viewer.userId), tier: viewer.tier }} />;
}

export default function PricingPage() {
  return (
    <>
      <PageHeader
        title="Plans"
        intro="Start on Free and move up when you want the full board. Online checkout isn't open yet: paid plans are switched on by hand for now."
      />
      <div className="mx-auto max-w-7xl px-4 pt-4 sm:px-6">
        <Suspense fallback={<PricingTiers />}>
          <Tiers />
        </Suspense>
      </div>

      <Section title="Compare plans">
        <div className="overflow-x-auto rounded-xl border border-navy-700">
          <table className="w-full min-w-[560px] border-collapse text-[0.95rem]">
            <caption className="sr-only">Feature comparison across Free, Plus and Pro.</caption>
            <thead className="bg-navy-850">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-[0.8rem] font-500 text-faint">Feature</th>
                <th scope="col" className="px-4 py-3 text-right font-display text-lg font-600 text-ink sm:text-center">Free</th>
                <th scope="col" className="px-4 py-3 text-right font-display text-lg font-600 text-model sm:text-center">Plus</th>
                <th scope="col" className="px-4 py-3 text-right font-display text-lg font-600 text-ink sm:text-center">Pro</th>
              </tr>
            </thead>
            {MATRIX.map((g) => (
              <tbody key={g.group} className="bg-navy-900">
                <tr className="border-t border-navy-700">
                  <th colSpan={4} scope="colgroup" className="bg-navy-900 px-4 pb-1 pt-5 text-left font-display text-base font-600 text-mute">
                    {g.group}
                  </th>
                </tr>
                {g.rows.map((r) => (
                  <tr key={r.label} className="border-t border-navy-700/50">
                    <th scope="row" className="px-4 py-3 text-left font-500 text-ink">{r.label}</th>
                    <td className="px-4 py-3 text-right sm:text-center"><Cell v={r.free} /></td>
                    <td className="bg-model/[0.04] px-4 py-3 text-right sm:text-center"><Cell v={r.plus} /></td>
                    <td className="px-4 py-3 text-right sm:text-center"><Cell v={r.pro} /></td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-faint">
          Prices are in US dollars, billed monthly. Model Room provides projections for information and entertainment
          and does not accept wagers.
        </p>
      </Section>
    </>
  );
}
