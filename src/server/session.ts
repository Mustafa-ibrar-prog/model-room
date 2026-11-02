import "server-only";

/**
 * The signed-in Model Room user (a Supabase auth user id), or null.
 *
 * Phase 2: no login exists yet, so this always returns null and every
 * visitor is anonymous Free. The Shopify Customer Account login described in
 * docs/auth-architecture.md will implement this by reading Model Room's
 * encrypted session cookie. Callers must already be inside <Suspense>,
 * because that implementation will read cookies.
 */
export async function getSessionUserId(): Promise<string | null> {
  return null;
}
