/**
 * Login configuration. Safe anywhere (no secrets): only checks whether the public Supabase settings exist
 * and which environment this is.
 */

/** Logins are on when the Supabase project URL and public (anon) key are configured. */
export function authEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
}

/** Vercel production deployment (customers). Test accounts never work here. */
export function isProduction(): boolean {
  return process.env.VERCEL_ENV === "production" || process.env.MODELROOM_ENV === "production";
}

export const TEST_ACCOUNT_DOMAIN = "@modelroom.test";

export function isTestAccount(email: string | null | undefined): boolean {
  return Boolean(email && email.toLowerCase().endsWith(TEST_ACCOUNT_DOMAIN));
}

/** Only relative, same-site paths are allowed as a post-login destination (no open redirects). */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (!next || typeof next !== "string") return fallback;
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (next.startsWith("/login") || next.startsWith("/signup") || next.startsWith("/auth/")) return fallback;
  return next;
}
