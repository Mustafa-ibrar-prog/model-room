import { afterEach, describe, expect, it, vi } from "vitest";
import { keyKind, publicSupabaseKey, secretSupabaseKey, supabaseConfigReport, supabaseUrl } from "@/lib/supabase/keys";

const jwt = (role: string) => `x.${btoa(JSON.stringify({ role, iss: "supabase" })).replace(/=+$/, "")}.sig`;

describe("Supabase key formats", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("recognises new and legacy keys", () => {
    expect(keyKind("sb_publishable_abc")).toBe("publishable");
    expect(keyKind("sb_secret_abc")).toBe("secret");
    expect(keyKind(jwt("anon"))).toBe("legacy-anon");
    expect(keyKind(jwt("service_role"))).toBe("legacy-service");
    expect(keyKind("nonsense")).toBe("unknown");
  });

  it("never treats a secret key as the browser key", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_secret_abc");
    expect(publicSupabaseKey()).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", jwt("service_role"));
    expect(publicSupabaseKey()).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_abc");
    expect(publicSupabaseKey()).toBe("sb_publishable_abc");
  });

  it("only accepts a real secret key on the server", () => {
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_publishable_abc");
    expect(secretSupabaseKey()).toBeNull();
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_abc");
    expect(secretSupabaseKey()).toBe("sb_secret_abc");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", jwt("service_role"));
    expect(secretSupabaseKey()).not.toBeNull();
  });

  it("accepts other common variable names and pasted quotes", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", ' "sb_publishable_abc" ');
    expect(publicSupabaseKey()).toBe("sb_publishable_abc");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    vi.stubEnv("SUPABASE_URL", "https://abc.supabase.co/");
    expect(supabaseUrl()).toBe("https://abc.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_abc");
    expect(secretSupabaseKey()).toBe("sb_secret_abc");
  });

  it("reports setup problems by name, never by value", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://abc.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_secret_TOPSECRET");
    const r = supabaseConfigReport();
    expect(r.ok).toBe(false);
    expect(r.lines.join(" ")).toContain("SECRET key");
    expect(r.lines.join(" ")).not.toContain("TOPSECRET");
  });
});
