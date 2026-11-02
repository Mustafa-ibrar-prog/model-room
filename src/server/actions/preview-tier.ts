"use server";

import { cookies } from "next/headers";
import { PREVIEW_COOKIE, isTierPreviewEnabled } from "@/server/viewer";
import type { TierId } from "@/types/domain";

/** Dev-only: switch the previewed plan. Does nothing unless ENABLE_TIER_PREVIEW=true. */
export async function setPreviewTier(tier: TierId): Promise<void> {
  if (!isTierPreviewEnabled()) return;
  if (tier !== "free" && tier !== "plus" && tier !== "pro") return;
  (await cookies()).set(PREVIEW_COOKIE, tier, { path: "/", sameSite: "lax", httpOnly: true });
}
