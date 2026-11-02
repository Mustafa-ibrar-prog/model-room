import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { TestSubscriptionControls } from "@/components/auth/TestSubscriptionControls";
import { Panel, TableSkeleton } from "@/components/ui/primitives";
import { tierName } from "@/config/tiers";
import { authEnabled, isProduction, isTestAccount } from "@/lib/auth-config";
import { formatTimestamp } from "@/lib/format";
import { signOut } from "@/server/actions/auth";
import { getMemberships, getTierForUser } from "@/server/membership";
import { getSessionUser } from "@/server/session";

export const metadata: Metadata = { title: "Account" };

const STATUS: Record<string, string> = {
  active: "Active", trialing: "Trial", past_due: "Payment overdue", paused: "Paused", cancelled: "Cancelled", expired: "Ended",
};

export default function AccountPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-14 sm:px-6">
      <h1 className="font-display text-4xl font-700 text-ink">Account</h1>
      <Suspense fallback={<TableSkeleton rows={4} />}>
        <Account />
      </Suspense>
    </div>
  );
}

async function Account() {
  if (!authEnabled()) {
    return <p className="mt-4 text-mute">Accounts aren&apos;t switched on for this site yet.</p>;
  }
  const user = await getSessionUser();
  if (!user) redirect("/login?next=/account");
  const [tier, memberships] = await Promise.all([getTierForUser(user.id), getMemberships(user.id)]);
  const live = memberships.find((m) => ["active", "trialing", "past_due", "cancelled"].includes(m.status));
  const testControls = !isProduction() && isTestAccount(user.email);
  return (
    <div className="mt-6 space-y-4">
      <Panel className="p-5">
        <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
          <dt className="text-faint">Email</dt>
          <dd className="text-ink">{user.email}</dd>
          <dt className="text-faint">Plan</dt>
          <dd className="font-display text-lg font-600 text-model">{tierName(tier)}</dd>
          <dt className="text-faint">Status</dt>
          <dd className="text-ink">{live ? STATUS[live.status] ?? live.status : tier === "free" ? "Free (no subscription)" : "Active"}</dd>
          {live?.current_period_end ? (
            <>
              <dt className="text-faint">{live.status === "cancelled" ? "Access ends" : "Renews"}</dt>
              <dd className="text-ink">{formatTimestamp(live.current_period_end)}</dd>
            </>
          ) : null}
        </dl>
        <form action={signOut} className="mt-5">
          <button type="submit" className="rounded-full border border-navy-600 px-4 py-2 text-sm text-ink hover:border-model">
            Sign out
          </button>
        </form>
      </Panel>
      {testControls ? (
        <Panel className="p-5">
          <h2 className="font-display text-xl font-600 text-ink">Test account controls</h2>
          <p className="mb-3 mt-1 text-sm text-mute">
            Test site only. These simulate a subscription change with no payment; access is then checked on the server exactly as for a paying customer.
          </p>
          <TestSubscriptionControls />
        </Panel>
      ) : null}
      {memberships.length ? (
        <Panel className="p-5">
          <h2 className="font-display text-xl font-600 text-ink">History</h2>
          <ul className="mt-2 space-y-1 text-sm text-mute">
            {memberships.slice(0, 10).map((m) => (
              <li key={m.id}>
                {tierName(m.tier)} · {STATUS[m.status] ?? m.status} · since {formatTimestamp(m.started_at)}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}
