import "server-only";
import { cache } from "react";
import { getSupabaseAdmin } from "@/lib/supabase/admin";
import { supabaseConfigReport } from "@/lib/supabase/keys";
import type { TierId } from "@/types/domain";

const TIERS: readonly TierId[] = ["free", "plus", "pro"];

/**
 * A user's effective plan, read from Supabase (public.effective_tier_for).
 *
 * The database decides: highest active membership wins, with the grace rules
 * in private.effective_tier(). Any failure resolves to "free" so an outage
 * can never unlock paid data. Cached per request.
 */
export const getTierLookup = cache(async (userId: string): Promise<{ tier: TierId; problem: string | null }> => {
  const db = getSupabaseAdmin();
  if (!db) {
    const why = supabaseConfigReport().lines.filter((l) => /server key|SECRET_KEY|SERVICE_ROLE/i.test(l)).join("; ");
    return { tier: "free", problem: `the server can't read plans: ${why || "server key not configured"}` };
  }

  const { data, error } = await db.rpc("effective_tier_for", { p_user: userId });
  if (error) {
    console.error("[membership] tier lookup failed; treating viewer as free", error.message);
    return { tier: "free", problem: `plan lookup failed: ${error.message}` };
  }
  return { tier: TIERS.includes(data as TierId) ? (data as TierId) : "free", problem: null };
});

export const getTierForUser = cache(async (userId: string): Promise<TierId> => (await getTierLookup(userId)).tier);

export interface MembershipRow {
  id: string;
  tier: TierId;
  status: string;
  source: string;
  current_period_end: string | null;
  ended_at: string | null;
  started_at: string;
  note: string | null;
}

/** The user's memberships, newest first (server only, service role). */
export async function getMemberships(userId: string): Promise<MembershipRow[]> {
  const db = getSupabaseAdmin();
  if (!db) return [];
  const { data, error } = await db
    .from("memberships")
    .select("id, tier, status, source, current_period_end, ended_at, started_at, note")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    console.error("[membership] list failed", error.message);
    return [];
  }
  return (data ?? []) as MembershipRow[];
}
