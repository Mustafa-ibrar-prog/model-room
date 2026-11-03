import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { secretSupabaseKey } from "./keys";

/**
 * Service-role Supabase client. Bypasses Row Level Security.
 *
 * - Server only: the "server-only" import makes any client-side import a
 *   build error, and the key has no NEXT_PUBLIC_ prefix so Next.js never
 *   inlines it into browser bundles.
 * - Use only inside src/server (data layer, membership lookups, webhooks).
 * - Returns null until SUPABASE_SERVICE_ROLE_KEY and NEXT_PUBLIC_SUPABASE_URL are set.
 */
let client: SupabaseClient | null | undefined;

export function getSupabaseAdmin(): SupabaseClient | null {
  if (client !== undefined) return client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = secretSupabaseKey(); // sb_secret_… or legacy service_role JWT
  client =
    url && serviceKey
      ? createClient(url, serviceKey, {
          auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
        })
      : null;
  return client;
}
