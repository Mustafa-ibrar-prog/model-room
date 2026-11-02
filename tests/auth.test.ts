/** Login rules that don't need a live Supabase project. */
import { afterEach, describe, expect, it } from "vitest";
import { authEnabled, isProduction, isTestAccount, safeNext } from "@/lib/auth-config";

const ENV = { ...process.env };
afterEach(() => {
  process.env = { ...ENV };
});

describe("login configuration", () => {
  it("only allows same-site return paths", () => {
    expect(safeNext("/props?nfl=2026_09_ARI_SEA#nfl")).toBe("/props?nfl=2026_09_ARI_SEA#nfl");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("/login?next=/x", "/account")).toBe("/account");
    expect(safeNext(undefined, "/account")).toBe("/account");
  });

  it("recognises test accounts and production", () => {
    expect(isTestAccount("Pro-Test@ModelRoom.test")).toBe(true);
    expect(isTestAccount("someone@gmail.com")).toBe(false);
    process.env.VERCEL_ENV = "preview";
    expect(isProduction()).toBe(false);
    process.env.VERCEL_ENV = "production";
    expect(isProduction()).toBe(true);
  });

  it("is off until the public Supabase settings exist", () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    expect(authEnabled()).toBe(false);
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://x.supabase.co";
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon";
    expect(authEnabled()).toBe(true);
  });
});

describe("plan switcher", () => {
  it("turns off once logins are configured, and never runs in production", async () => {
    const { isTierPreviewEnabled } = await import("@/server/viewer");
    process.env.ENABLE_TIER_PREVIEW = "true";
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.VERCEL_ENV;
    expect(isTierPreviewEnabled()).toBe(true);
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://x.supabase.co";
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon";
    expect(isTierPreviewEnabled()).toBe(false);
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    process.env.VERCEL_ENV = "production";
    expect(isTierPreviewEnabled()).toBe(false);
  });
});
