"use server";

import { revalidatePath } from "next/cache";
import { isProduction, isTestAccount } from "@/lib/auth-config";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { getSessionUser } from "@/server/session";

/**
 * Simulated subscription changes for test accounts on the test site. Never in production, never for real
 * accounts. Runs as the signed-in user through public.test_simulate_membership(), which writes the normal
 * memberships table and refuses unless the database has test controls switched on and the caller is a
 * confirmed @modelroom.test account. Access is then checked on the server exactly as for a paying customer.
 */
type Change = "plus" | "pro" | "free" | "cancel" | "expire";
const CHANGES: readonly Change[] = ["plus", "pro", "free", "cancel", "expire"];

export async function simulateSubscription(change: Change): Promise<{ ok: boolean; error?: string; tier?: string }> {
  if (isProduction()) return { ok: false, error: "Not available in production." };
  if (!CHANGES.includes(change)) return { ok: false, error: "Unknown change." };
  const user = await getSessionUser();
  if (!user || !isTestAccount(user.email)) return { ok: false, error: "Only test accounts can simulate subscriptions." };
  const db = await createSupabaseServerClient();
  if (!db) return { ok: false, error: "Logins aren't configured on this deployment." };
  const { data, error } = await db.rpc("test_simulate_membership", { p_change: change });
  if (error) return { ok: false, error: error.message };
  revalidatePath("/", "layout");
  return { ok: true, tier: String(data) };
}
