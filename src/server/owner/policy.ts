/**
 * Who may open the owner dashboard. Pure and dependency-free so the request proxy (which runs before any page
 * renders) and the server components share one rule. Fails closed on every doubt:
 *
 *   - never in production (the route does not exist there),
 *   - OWNER_EMAILS (server-only env) must hold exactly ONE well-formed address: unset, empty, a list of two or more,
 *     or a malformed value turns the dashboard off for everyone,
 *   - test accounts (@modelroom.test) are never the owner, whatever OWNER_EMAILS says,
 *   - the signed-in user's verified email must equal that address (case-insensitive).
 *
 * The tier-preview cookie and subscription tiers play no part: Pro is not the owner.
 */
import { isProduction, isTestAccount } from "@/lib/auth-config";

export type OwnerConfig =
  | { ok: true; email: string }
  | { ok: false; reason: "production" | "unset" | "not_exactly_one" | "invalid" | "test_account" };

const EMAIL = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

export function ownerConfig(env: Record<string, string | undefined> = process.env): OwnerConfig {
  if (isProduction()) return { ok: false, reason: "production" };
  const list = (env.OWNER_EMAILS ?? "").split(/[,;\s]+/).map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!list.length) return { ok: false, reason: "unset" };
  if (list.length !== 1) return { ok: false, reason: "not_exactly_one" };
  if (!EMAIL.test(list[0])) return { ok: false, reason: "invalid" };
  if (isTestAccount(list[0])) return { ok: false, reason: "test_account" };
  return { ok: true, email: list[0] };
}

export function isOwnerEmail(email: string | null | undefined, env?: Record<string, string | undefined>): boolean {
  if (!email) return false;
  const c = ownerConfig(env);
  return c.ok && !isTestAccount(email) && email.trim().toLowerCase() === c.email;
}

/** Paths that belong to the owner dashboard (pages and their RSC requests). */
export const isOwnerPath = (pathname: string) => pathname === "/owner" || pathname.startsWith("/owner/");

/**
 * Local design and testing only: under `next dev` on a developer machine (never a Vercel build, never production),
 * MODELROOM_DEV_SESSION_EMAIL stands in for the signed-in user's email so the owner check can be exercised without
 * the TEST Supabase project. Ignored everywhere else.
 */
export function devSessionEmail(): string | null {
  if (process.env.NODE_ENV !== "development" || process.env.VERCEL || isProduction()) return null;
  return process.env.MODELROOM_DEV_SESSION_EMAIL?.trim() || null;
}
