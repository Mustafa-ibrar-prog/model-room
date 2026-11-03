import Link from "next/link";
import { PLANS, TIER_ORDER, tierName } from "@/config/tiers";
import type { TierId } from "@/types/domain";
import { formatPrice } from "@/lib/format";

function Check({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={`h-4 w-4 shrink-0 ${className}`} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 8.5l3 3 7-7" />
    </svg>
  );
}

function Cross() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

/** Who is looking, as resolved on the server: decides each plan's button. */
export interface PricingViewer {
  authOn: boolean;
  signedIn: boolean;
  tier: TierId;
}

function Cta({ plan, featured, viewer }: { plan: TierId; featured: boolean; viewer: PricingViewer }) {
  const solid = `block rounded-full px-4 py-2.5 text-center font-600 ${featured ? "bg-model text-navy-950 hover:bg-model/90" : "bg-navy-800 text-ink hover:bg-navy-700"}`;
  const quiet = "block rounded-full border border-navy-600 px-4 py-2.5 text-center font-600 text-ink hover:border-mute";
  const done = "block w-full cursor-default rounded-full border border-navy-700 px-4 py-2.5 text-center font-600 text-mute";
  const have = TIER_ORDER.indexOf(viewer.tier) >= TIER_ORDER.indexOf(plan);
  if (viewer.signedIn && viewer.tier === plan) return <span className={done}>Your plan</span>;
  if (plan === "free") return <Link href="/nfl" className={quiet}>{viewer.signedIn ? "Included" : "Use Free now"}</Link>;
  if (viewer.signedIn && have) return <span className={done}>Included in {tierName(viewer.tier)}</span>;
  if (!viewer.authOn) return <span className={done}>Checkout opens soon</span>;
  const upgrade = `/upgrade?requires=${plan}&next=${encodeURIComponent("/pricing")}`;
  if (!viewer.signedIn) return <Link href={`/signup?next=${encodeURIComponent(upgrade)}`} className={solid}>Sign up for {tierName(plan)}</Link>;
  return <Link href={upgrade} className={solid}>Get {tierName(plan)}</Link>;
}

export function PricingTiers({ viewer = { authOn: false, signedIn: false, tier: "free" } }: { viewer?: PricingViewer }) {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      {PLANS.map((plan) => {
        const featured = plan.id === "plus";
        return (
          <article
            key={plan.id}
            aria-labelledby={`plan-${plan.id}`}
            className={`relative flex flex-col rounded-2xl border p-6 sm:p-7 ${
              featured ? "border-model/70 bg-navy-850 ring-1 ring-model/30" : "border-navy-700 bg-navy-900"
            }`}
          >
            {featured && (
              <span className="absolute -top-3 left-6 rounded-full bg-model px-3 py-0.5 text-[0.8rem] font-600 text-navy-950">
                Most popular
              </span>
            )}
            <h2 id={`plan-${plan.id}`} className="font-display text-2xl font-700 text-ink">
              {plan.name}
            </h2>
            <p className="mt-2 min-h-[3rem] text-[0.95rem] leading-relaxed text-mute">{plan.summary}</p>
            <p className="mt-5 flex items-baseline gap-1.5">
              <span className={`font-display text-5xl font-700 leading-none ${featured ? "text-model" : "text-ink"}`}>
                {formatPrice(plan.priceMonthly)}
              </span>
              <span className="text-mute">per month</span>
            </p>

            <ul className="mt-6 flex-1 space-y-3 text-[0.95rem]">
              {plan.features.map((f) => (
                <li key={f} className="flex gap-2.5 text-ink/90">
                  <Check className={featured ? "mt-0.5 text-model" : "mt-0.5 text-market"} />
                  {f}
                </li>
              ))}
              {plan.excluded?.map((f) => (
                <li key={f} className="flex gap-2.5 text-faint">
                  <span className="mt-0.5"><Cross /></span>
                  <span>
                    <span className="sr-only">Not included: </span>
                    {f}
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-7">
              <Cta plan={plan.id} featured={featured} viewer={viewer} />
            </div>
          </article>
        );
      })}
    </div>
  );
}
