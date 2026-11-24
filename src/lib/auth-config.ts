/**
 * Login configuration. Safe anywhere (no secrets): only checks whether the public Supabase settings exist
 * and which environment this is.
 */
import { publicSupabaseKey, supabaseUrl } from "./supabase/keys";

/** Logins are on when the Supabase project URL and a public key (publishable or legacy anon) are configured. */
export function authEnabled(): boolean {
  return Boolean(supabaseUrl() && publicSupabaseKey());
}

/** Vercel production deployment (customers). Test accounts never work here. */
export function isProduction(): boolean {
  return process.env.VERCEL_ENV === "production" || process.env.MODELROOM_ENV === "production";
}

/**
 * TEST-site open access (Moose, 2026-11-23: "just remove password access for now"): while the TEST Supabase project
 * is restricted, logins can't work, so on non-production sites every visitor gets full (Pro) access with no account
 * and no password. Production never: isProduction() wins. To bring logins back, set MODELROOM_TEST_OPEN_ACCESS=off
 * in the TEST site's Vercel settings (or revert this). Nothing about accounts, plans or passwords is changed.
 */
export function testOpenAccess(): boolean {
  return !isProduction() && process.env.MODELROOM_TEST_OPEN_ACCESS !== "off";
}

export const TEST_ACCOUNT_DOMAIN = "@modelroom.test";

export function isTestAccount(email: string | null | undefined): boolean {
  return Boolean(email && email.toLowerCase().endsWith(TEST_ACCOUNT_DOMAIN));
}

/**
 * Test-account passwords come only from the TEST_ACCOUNT_PASSWORD secret via the setup workflow. Changing one on the
 * site would silently leave the automated login checks (and everyone else using the test accounts) out of sync, so
 * the site never sends a reset email to, or changes the password of, a test account. Real customers are unaffected.
 */
export function passwordChangeAllowed(email: string | null | undefined): boolean {
  return !isTestAccount(email);
}

/** Only relative, same-site paths are allowed as a post-login destination (no open redirects). */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (!next || typeof next !== "string") return fallback;
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (next.startsWith("/login") || next.startsWith("/signup") || next.startsWith("/auth/")) return fallback;
  return next;
}
