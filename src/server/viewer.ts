import "server-only";
import { cookies } from "next/headers";
import { authEnabled, isProduction } from "@/lib/auth-config";
import { getTierForUser } from "./membership";
import { getSessionUserId } from "./session";
import type { TierId } from "@/types/domain";

export interface Viewer {
  userId: string | null;
  tier: TierId;
  /** True when the tier came from the dev-only preview switcher. */
  isPreview: boolean;
}

export const PREVIEW_COOKIE = "mr_preview_tier";

/**
 * The plan switcher exists only for testing before logins are set up. Once logins are configured it
 * is off everywhere, so a plan can only come from a real (or test) account's membership.
 */
export function isTierPreviewEnabled(): boolean {
  return process.env.ENABLE_TIER_PREVIEW === "true" && !authEnabled() && !isProduction();
}

/**
 * Resolve who is viewing and which plan they hold.
 *
 * 1. Signed-in user: tier comes from Supabase memberships via
 *    public.effective_tier_for(). Not active until Shopify login ships;
 *    getSessionUserId() returns null in Phase 2.
 * 2. ENABLE_TIER_PREVIEW=true: a dev cookie previews Plus/Pro layouts.
 * 3. Otherwise: anonymous Free.
 *
 * Callers must render inside <Suspense> because this reads cookies.
 */
export async function getViewer(): Promise<Viewer> {
  const userId = await getSessionUserId();
  if (userId) {
    return { userId, tier: await getTierForUser(userId), isPreview: false };
  }

  if (isTierPreviewEnabled()) {
    const value = (await cookies()).get(PREVIEW_COOKIE)?.value;
    if (value === "plus" || value === "pro" || value === "free") {
      return { userId: null, tier: value, isPreview: true };
    }
  }
  return { userId: null, tier: "free", isPreview: false };
}
