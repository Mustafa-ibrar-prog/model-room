import "server-only";
import { cache } from "react";
import { getSupabaseAdmin } from "@/lib/supabase/admin";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { getSessionUser } from "@/server/session";
import type { TierId } from "@/types/domain";

const TIERS: readonly TierId[] = ["free", "plus", "pro"];

/**
 * A user's effective plan, read from Supabase on the server.
 *
 * For the signed-in viewer (every current caller) it is read AS THAT USER: public.my_tier() with their
 * session, so the database decides from auth.uid() and the row-level security policies apply. No
 * service-role key is needed. Looking up anyone else needs the service role (effective_tier_for).
 * The database's rules decide (highest active membership, grace period). Any failure resolves to
 * "free", so an outage can never unlock paid data. Cached per request.
 */
export const getTierLookup = cache(async (userId: string): Promise<{ tier: TierId; problem: string | null }> => {
  const me = await getSessionUser();
  if (me?.id === userId) {
    const db = await createSupabaseServerClient();
    if (!db) return { tier: "free", problem: "logins aren't configured" };
    const { data, error } = await db.rpc("my_tier");
    if (error) {
      console.error("[membership] tier lookup failed; treating viewer as free", error.message);
      return { tier: "free", problem: `plan lookup failed: ${error.message}` };
    }
    return { tier: TIERS.includes(data as TierId) ? (data as TierId) : "free", problem: null };
  }
  const admin = getSupabaseAdmin();
  if (!admin) return { tier: "free", problem: "looking up another user's plan needs the server key" };
  const { data, error } = await admin.rpc("effective_tier_for", { p_user: userId });
  if (error) return { tier: "free", problem: `plan lookup failed: ${error.message}` };
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

/** The signed-in user's memberships, newest first. Read as the user: RLS returns only their own rows. */
export async function getMemberships(userId: string): Promise<MembershipRow[]> {
  const me = await getSessionUser();
  const db = me?.id === userId ? await createSupabaseServerClient() : getSupabaseAdmin();
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
