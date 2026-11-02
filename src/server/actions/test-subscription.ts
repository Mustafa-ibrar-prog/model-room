"use server";

import { revalidatePath } from "next/cache";
import { isProduction, isTestAccount } from "@/lib/auth-config";
import { getSupabaseAdmin } from "@/lib/supabase/admin";
import { getSessionUser } from "@/server/session";

/**
 * Simulated subscription changes for test accounts on the test site. Never available in production,
 * never for real accounts. Writes go through the same memberships table the paid flow will use, so
 * the server-side access checks are exactly the real ones.
 */
type Change = "plus" | "pro" | "free" | "cancel" | "expire";

export async function simulateSubscription(change: Change): Promise<{ ok: boolean; error?: string }> {
  if (isProduction()) return { ok: false, error: "Not available in production." };
  const user = await getSessionUser();
  if (!user || !isTestAccount(user.email)) return { ok: false, error: "Only test accounts can simulate subscriptions." };
  const db = getSupabaseAdmin();
  if (!db) return { ok: false, error: "The database isn't connected." };
  const now = new Date();
  const { data: live } = await db
    .from("memberships")
    .select("id, tier, status")
    .eq("user_id", user.id)
    .in("status", ["active", "trialing", "past_due", "cancelled"]);
  const current = live ?? [];
  const endAll = async () => {
    for (const m of current) {
      await db.from("memberships").update({ status: "expired", ended_at: now.toISOString() }).eq("id", m.id);
    }
  };
  if (change === "plus" || change === "pro") {
    await endAll();
    const periodEnd = new Date(now.getTime() + 30 * 86400_000).toISOString();
    const { error } = await db.from("memberships").insert({
      user_id: user.id, tier: change, status: "active", source: "admin", current_period_end: periodEnd,
      note: "Test account: simulated subscription (no payment)",
    });
    if (error) return { ok: false, error: error.message };
  } else if (change === "free") {
    await endAll();
  } else if (change === "cancel") {
    // Cancelled: access continues until the end of the paid period, then stops.
    for (const m of current) {
      const end = new Date(now.getTime() + 7 * 86400_000).toISOString();
      await db.from("memberships").update({ status: "cancelled", current_period_end: end }).eq("id", m.id);
    }
  } else if (change === "expire") {
    await endAll();
  }
  revalidatePath("/", "layout");
  return { ok: true };
}
