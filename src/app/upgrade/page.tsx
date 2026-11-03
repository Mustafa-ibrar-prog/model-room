import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { Panel } from "@/components/ui/primitives";
import { TIER_ORDER, tierName } from "@/config/tiers";
import { authEnabled, isProduction, isTestAccount, safeNext } from "@/lib/auth-config";
import { getSessionUser } from "@/server/session";
import { getViewer } from "@/server/viewer";
import type { TierId } from "@/types/domain";

export const metadata: Metadata = { title: "Unlock" };

type SP = Promise<{ requires?: string; next?: string }>;

export default function UpgradePage({ searchParams }: { searchParams: SP }) {
  return (
    <div className="mx-auto max-w-md px-4 py-14 sm:px-6">
      <Suspense fallback={null}>
        <Upgrade searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Upgrade({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const requires: TierId = sp.requires === "pro" ? "pro" : "plus";
  const next = safeNext(sp.next, "/");
  const viewer = await getViewer();
  const user = viewer.userId ? await getSessionUser() : null;
  const testAccount = !isProduction() && isTestAccount(user?.email);
  const has = TIER_ORDER.indexOf(viewer.tier) >= TIER_ORDER.indexOf(requires);
  const q = `next=${encodeURIComponent(next)}&requires=${requires}`;
  return (
    <>
      <h1 className="font-display text-4xl font-700 text-ink">{has ? "You're all set" : `Part of ${tierName(requires)}`}</h1>
      <Panel className="mt-6 space-y-4 p-6">
        {has ? (
          <Link href={next} className="block rounded-full bg-model px-4 py-2.5 text-center font-600 text-navy-950">Go back</Link>
        ) : !authEnabled() ? (
          <p className="text-sm text-mute">Accounts aren&apos;t switched on for this site yet. See <Link href="/pricing" className="text-model">plans</Link>.</p>
        ) : viewer.userId ? (
          <>
            <p className="text-sm text-mute">
              Your account is on {tierName(viewer.tier)}. {tierName(requires)} includes this. Online checkout isn&apos;t open yet: during testing,
              paid plans are switched on by hand.
            </p>
            {testAccount ? (
              <Link href="/account" className="block rounded-full bg-model px-4 py-2.5 text-center font-600 text-navy-950">Simulate {tierName(requires)} on this test account</Link>
            ) : null}
            <Link href="/pricing" className="block rounded-full border border-navy-600 px-4 py-2.5 text-center text-ink">Compare plans</Link>
          </>
        ) : (
          <>
            <p className="text-sm text-mute">Log in to an account with {tierName(requires)}, and you&apos;ll go straight back to what you were looking at.</p>
            <Link href={`/login?${q}`} className="block rounded-full bg-model px-4 py-2.5 text-center font-600 text-navy-950">Log in</Link>
            <Link href={`/signup?next=${encodeURIComponent(next)}`} className="block rounded-full border border-navy-600 px-4 py-2.5 text-center text-ink">Create an account</Link>
            <Link href="/pricing" className="block text-center text-sm text-model">Compare plans</Link>
          </>
        )}
      </Panel>
    </>
  );
}
