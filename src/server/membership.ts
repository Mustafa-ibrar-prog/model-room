import "server-only";
import { cache } from "react";
import { getSupabaseAdmin } from "@/lib/supabase/admin";
import type { TierId } from "@/types/domain";

const TIERS: readonly TierId[] = ["free", "plus", "pro"];

/**
 * A user's effective plan, read from Supabase (public.effective_tier_for).
 *
 * The database decides: highest active membership wins, with the grace rules
 * in private.effective_tier(). Any failure resolves to "free" so an outage
 * can never unlock paid data. Cached per request.
 */
export const getTierForUser = cache(async (userId: string): Promise<TierId> => {
  const db = getSupabaseAdmin();
  if (!db) return "free";

  const { data, error } = await db.rpc("effective_tier_for", { p_user: userId });
  if (error) {
    console.error("[membership] tier lookup failed; treating viewer as free", error.message);
    return "free";
  }
  return TIERS.includes(data as TierId) ? (data as TierId) : "free";
});
