// Creates the three test accounts on the TEST SITE's Supabase project and gives each its plan.
// No payments: memberships are written as admin grants marked "test account".
//
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, TEST_ACCOUNT_PASSWORD   (GitHub Actions secrets)
//   MODELROOM_TARGET=preview                                         (required; refuses anything else)
//
// Run by .github/workflows/supabase-preview.yml. Safe to re-run: existing accounts get their password and
// plan reset to the starting state.
import { createClient } from "@supabase/supabase-js";

const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, TEST_ACCOUNT_PASSWORD, MODELROOM_TARGET, VERCEL_ENV, MODELROOM_ENV } = process.env;
if (MODELROOM_TARGET !== "preview" || VERCEL_ENV === "production" || MODELROOM_ENV === "production") {
  console.error("Refusing: test accounts are only created for the test site (MODELROOM_TARGET=preview).");
  process.exit(1);
}
if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY || !TEST_ACCOUNT_PASSWORD) {
  console.error("Missing SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY or TEST_ACCOUNT_PASSWORD.");
  process.exit(1);
}

const ACCOUNTS = [
  { email: "free-test@modelroom.test", tier: null },
  { email: "plus-test@modelroom.test", tier: "plus" },
  { email: "pro-test@modelroom.test", tier: "pro" },
];

const db = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });

async function findUser(email) {
  for (let page = 1; page < 50; page++) {
    const { data, error } = await db.auth.admin.listUsers({ page, perPage: 200 });
    if (error) throw error;
    const hit = data.users.find((u) => (u.email ?? "").toLowerCase() === email);
    if (hit || data.users.length < 200) return hit ?? null;
  }
  return null;
}

for (const a of ACCOUNTS) {
  let user = await findUser(a.email);
  if (user) {
    const { error } = await db.auth.admin.updateUserById(user.id, { password: TEST_ACCOUNT_PASSWORD, email_confirm: true });
    if (error) throw error;
  } else {
    const { data, error } = await db.auth.admin.createUser({ email: a.email, password: TEST_ACCOUNT_PASSWORD, email_confirm: true });
    if (error) throw error;
    user = data.user;
  }
  // Reset to the starting plan: end anything live, then grant the account's tier.
  const now = new Date().toISOString();
  const { error: endErr } = await db.from("memberships").update({ status: "expired", ended_at: now })
    .eq("user_id", user.id).in("status", ["active", "trialing", "past_due", "cancelled", "paused"]);
  if (endErr) throw endErr;
  if (a.tier) {
    const periodEnd = new Date(Date.now() + 365 * 86400_000).toISOString();
    const { error } = await db.from("memberships").insert({
      user_id: user.id, tier: a.tier, status: "active", source: "admin", current_period_end: periodEnd,
      note: "Test account: simulated subscription (no payment)",
    });
    if (error) throw error;
  }
  console.log(`${a.email}: ready (${a.tier ?? "free"})`);
}
