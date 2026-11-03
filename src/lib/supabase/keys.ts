/**
 * Supabase key checks. Supabase has two key formats:
 * - new: sb_publishable_… (browser-safe) and sb_secret_… (server only)
 * - legacy: JWTs whose payload role is "anon" or "service_role"
 * Both work with supabase-js. These checks stop a key being used in the wrong place; they never log the key.
 */
export type KeyKind = "publishable" | "secret" | "legacy-anon" | "legacy-service" | "unknown";

export function keyKind(key: string | undefined | null): KeyKind {
  if (!key) return "unknown";
  if (key.startsWith("sb_publishable_")) return "publishable";
  if (key.startsWith("sb_secret_")) return "secret";
  const parts = key.split(".");
  if (parts.length === 3) {
    try {
      const json = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(parts[1].length / 4) * 4, "=")));
      if (json.role === "anon") return "legacy-anon";
      if (json.role === "service_role") return "legacy-service";
    } catch {
      return "unknown";
    }
  }
  return "unknown";
}

/** The browser key, or null if it is missing or is actually a secret key (which must never reach a browser). */
export function publicSupabaseKey(): string | null {
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const kind = keyKind(key);
  return kind === "publishable" || kind === "legacy-anon" ? key! : null;
}

/** The server key, or null if it is missing or is a public key (which can't bypass row-level security). */
export function secretSupabaseKey(): string | null {
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  const kind = keyKind(key);
  return kind === "secret" || kind === "legacy-service" ? key! : null;
}
