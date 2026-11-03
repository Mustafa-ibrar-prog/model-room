import Link from "next/link";
import { tierName } from "@/config/tiers";
import { authEnabled, isProduction } from "@/lib/auth-config";
import { signOut } from "@/server/actions/auth";
import { getTierForUser } from "@/server/membership";
import { getSessionUser } from "@/server/session";
import type { TierId } from "@/types/domain";
import { Dropdown } from "./Dropdown";

const BADGE: Record<TierId, string> = {
  free: "border border-navy-600 text-mute",
  plus: "bg-model/15 text-model",
  pro: "bg-model text-navy-950",
};

export function PlanBadge({ tier }: { tier: TierId }) {
  return <span className={`rounded px-1.5 py-px text-[0.7rem] font-600 uppercase tracking-wider ${BADGE[tier]}`}>{tierName(tier)}</span>;
}

/**
 * Header account area. Signed out: Log in and Sign up. Signed in: an Account menu with the plan the
 * server resolved from Supabase memberships, and Log out. On the test site the buttons show even when
 * logins aren't configured, so the sign-in page can explain what's missing; in production they don't.
 */
export async function AccountMenu({ variant }: { variant: "desktop" | "mobile" }) {
  if (!authEnabled() && isProduction()) return null;
  const user = authEnabled() ? await getSessionUser() : null;

  if (!user) {
    return variant === "desktop" ? (
      <div className="flex items-center gap-2">
        <Link href="/login" className="rounded-md px-3 py-2 text-sm font-500 text-ink hover:text-model">Log in</Link>
        <Link href="/signup" className="rounded-full border border-navy-600 px-4 py-2 text-sm font-600 text-ink hover:border-model">Sign up</Link>
      </div>
    ) : (
      <div className="grid grid-cols-2 gap-2">
        <Link href="/login" className="rounded-full border border-navy-600 px-4 py-2.5 text-center font-600 text-ink">Log in</Link>
        <Link href="/signup" className="rounded-full bg-model px-4 py-2.5 text-center font-600 text-navy-950">Sign up</Link>
      </div>
    );
  }

  const tier = await getTierForUser(user.id);
  const email = user.email ?? "Signed in";
  const items = (
    <>
      <Link href="/account" className="block rounded-md px-3 py-2 text-sm text-ink hover:bg-navy-800">Account and plan</Link>
      {tier !== "pro" ? <Link href="/pricing" className="block rounded-md px-3 py-2 text-sm text-model hover:bg-navy-800">Upgrade</Link> : null}
      <form action={signOut}>
        <button type="submit" className="block w-full rounded-md px-3 py-2 text-left text-sm text-ink hover:bg-navy-800">Log out</button>
      </form>
    </>
  );

  if (variant === "mobile") {
    return (
      <div className="rounded-lg border border-navy-700 bg-navy-900 p-2">
        <div className="flex items-center justify-between gap-2 px-3 py-1.5">
          <span className="truncate text-sm text-mute">{email}</span>
          <PlanBadge tier={tier} />
        </div>
        {items}
      </div>
    );
  }

  return (
    <Dropdown
      label={`Account menu, ${tierName(tier)} plan`}
      summary={
        <>
          <span aria-hidden="true" className="flex h-7 w-7 items-center justify-center rounded-full bg-navy-800 font-display text-sm font-700 uppercase text-ink">
            {email.slice(0, 1)}
          </span>
          <span className="text-sm text-ink">Account</span>
          <PlanBadge tier={tier} />
        </>
      }
    >
      <div className="border-b border-navy-700 px-3 pb-2 pt-1">
        <div className="truncate text-sm text-ink">{email}</div>
        <div className="mt-0.5 text-xs text-mute">Plan: <span className="font-600 text-ink">{tierName(tier)}</span></div>
      </div>
      <div className="pt-1">{items}</div>
    </Dropdown>
  );
}
