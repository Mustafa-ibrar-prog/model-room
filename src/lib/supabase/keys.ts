/**
 * Supabase settings. Supabase has two key formats:
 * - new: sb_publishable_… (browser-safe) and sb_secret_… (server only)
 * - legacy: JWTs whose payload role is "anon" or "service_role"
 * Both work with supabase-js. The variable names vary by setup (Supabase docs, the Vercel integration,
 * this repo's docs), so several are accepted. A key is never used in the wrong place, and never logged.
 */
export type KeyKind = "publishable" | "secret" | "legacy-anon" | "legacy-service" | "unknown";

export const URL_VARS = ["NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL"] as const;
export const PUBLIC_KEY_VARS = [
  "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
  "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_ANON_KEY",
] as const;
export const SECRET_KEY_VARS = ["SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"] as const;

/** Trim whitespace and stray quotes that often come along when a value is pasted. */
function clean(v: string | undefined): string | undefined {
  const t = v?.trim().replace(/^["']|["']$/g, "").trim();
  return t ? t : undefined;
}

function read(names: readonly string[]): { name: string; value: string } | null {
  for (const name of names) {
    const value = clean(process.env[name]);
    if (value) return { name, value };
  }
  return null;
}

export function keyKind(key: string | undefined | null): KeyKind {
  if (!key) return "unknown";
  if (key.startsWith("sb_publishable_")) return "publishable";
  if (key.startsWith("sb_secret_")) return "secret";
  const parts = key.split(".");
  if (parts.length === 3) {
    try {
      const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      const json = JSON.parse(atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, "=")));
      if (json.role === "anon") return "legacy-anon";
      if (json.role === "service_role") return "legacy-service";
    } catch {
      return "unknown";
    }
  }
  return "unknown";
}

export function supabaseUrl(): string | null {
  const v = read(URL_VARS)?.value;
  if (!v) return null;
  try {
    const u = new URL(v);
    return u.protocol === "https:" || u.hostname === "localhost" || u.hostname === "127.0.0.1" ? u.origin : null;
  } catch {
    return null;
  }
}

/** The browser key, or null if missing or actually a secret key (which must never reach a browser). */
export function publicSupabaseKey(): string | null {
  for (const name of PUBLIC_KEY_VARS) {
    const v = clean(process.env[name]);
    const kind = keyKind(v);
    if (kind === "publishable" || kind === "legacy-anon") return v!;
  }
  return null;
}

/** The server key, or null if missing or a public key (which can't bypass row-level security). */
export function secretSupabaseKey(): string | null {
  for (const name of SECRET_KEY_VARS) {
    const v = clean(process.env[name]);
    const kind = keyKind(v);
    if (kind === "secret" || kind === "legacy-service") return v!;
  }
  return null;
}

/**
 * What is configured, without values: variable names and key kinds only. Shown on the test site's
 * sign-in page when logins are off, so a setup mistake can be fixed without reading server logs.
 */
export function supabaseConfigReport(): { ok: boolean; lines: string[] } {
  const lines: string[] = [];
  const url = read(URL_VARS);
  if (!url) lines.push(`Project URL: missing (set ${URL_VARS[0]})`);
  else lines.push(supabaseUrl() ? `Project URL: found in ${url.name}` : `Project URL in ${url.name} isn't a valid https:// URL`);
  const pub = PUBLIC_KEY_VARS.map((n) => ({ n, k: clean(process.env[n]) })).filter((x) => x.k);
  if (!pub.length) lines.push(`Public key: missing (set ${PUBLIC_KEY_VARS[2]} or ${PUBLIC_KEY_VARS[0]} to the publishable or anon key)`);
  for (const { n, k } of pub) {
    const kind = keyKind(k);
    lines.push(
      kind === "publishable" || kind === "legacy-anon"
        ? `Public key: ${kind === "publishable" ? "publishable (sb_publishable_…)" : "legacy anon"} key in ${n}`
        : kind === "secret" || kind === "legacy-service"
          ? `${n} holds a SECRET key. It was refused so it can't reach browsers; use the publishable key there`
          : `${n} doesn't look like a Supabase key`,
    );
  }
  const sec = SECRET_KEY_VARS.map((n) => ({ n, k: clean(process.env[n]) })).filter((x) => x.k);
  if (!sec.length) lines.push(`Server key: missing (set ${SECRET_KEY_VARS[1]}; needed for plans)`);
  for (const { n, k } of sec) {
    const kind = keyKind(k);
    lines.push(kind === "secret" || kind === "legacy-service" ? `Server key: ${kind === "secret" ? "secret (sb_secret_…)" : "legacy service_role"} key in ${n}` : `${n} isn't a secret key`);
  }
  return { ok: Boolean(supabaseUrl() && publicSupabaseKey() && secretSupabaseKey()), lines };
}
