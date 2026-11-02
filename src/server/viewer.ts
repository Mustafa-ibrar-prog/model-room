import "server-only";
import { cookies } from "next/headers";
import type { TierId } from "@/types/domain";

export interface Viewer {
  userId: string | null;
  tier: TierId;
  /** True when the tier came from the dev-only preview switcher. */
  isPreview: boolean;
}

export const PREVIEW_COOKIE = "mr_preview_tier";

export function isTierPreviewEnabled(): boolean {
  return process.env.ENABLE_TIER_PREVIEW === "true";
}

/**
 * Resolve who is viewing and which plan they hold.
 *
 * Phase 1: everyone is an anonymous Free viewer. If ENABLE_TIER_PREVIEW=true,
 * a cookie lets you preview Plus/Pro layouts during development.
 *
 * Phase 2+: replace the body with a Supabase session lookup plus a
 * subscription check (see src/lib/supabase/server.ts). Keep the return shape.
 * Callers must render inside <Suspense> because this reads cookies.
 */
export async function getViewer(): Promise<Viewer> {
  if (isTierPreviewEnabled()) {
    const value = (await cookies()).get(PREVIEW_COOKIE)?.value;
    if (value === "plus" || value === "pro" || value === "free") {
      return { userId: null, tier: value, isPreview: true };
    }
  }
  return { userId: null, tier: "free", isPreview: false };
}
