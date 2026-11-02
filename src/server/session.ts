import "server-only";
import { cache } from "react";
import { authEnabled, isProduction, isTestAccount } from "@/lib/auth-config";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export interface SessionUser {
  id: string;
  email: string | null;
}

/**
 * The signed-in user, verified with Supabase Auth (getUser() checks the token with the auth server,
 * unlike getSession(), which only decodes the cookie). Null when logged out or when logins aren't
 * configured. Test accounts are refused in production. Callers must be inside <Suspense> (reads cookies).
 */
export const getSessionUser = cache(async (): Promise<SessionUser | null> => {
  if (!authEnabled()) return null;
  const supabase = await createSupabaseServerClient();
  if (!supabase) return null;
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) return null;
  if (isProduction() && isTestAccount(data.user.email)) return null;
  return { id: data.user.id, email: data.user.email ?? null };
});

export async function getSessionUserId(): Promise<string | null> {
  return (await getSessionUser())?.id ?? null;
}
