import { afterEach, describe, expect, it } from "vitest";
import { devSessionEmail, isOwnerEmail, isOwnerPath, ownerConfig } from "@/server/owner/policy";

const env = (OWNER_EMAILS?: string) => ({ OWNER_EMAILS });
const saved = { ...process.env };
afterEach(() => {
  for (const k of ["VERCEL_ENV", "MODELROOM_ENV", "VERCEL", "MODELROOM_DEV_SESSION_EMAIL"]) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
});

describe("owner dashboard policy (fails closed)", () => {
  it("accepts exactly one well-formed owner address, case-insensitively", () => {
    expect(ownerConfig(env("Owner@Example.com"))).toEqual({ ok: true, email: "owner@example.com" });
    expect(isOwnerEmail("OWNER@example.com", env("owner@example.com"))).toBe(true);
    expect(isOwnerEmail("someone@example.com", env("owner@example.com"))).toBe(false);
  });

  it("is off for everyone when the setting is missing, a list, malformed or a test account", () => {
    expect(ownerConfig(env(undefined))).toEqual({ ok: false, reason: "unset" });
    expect(ownerConfig(env("  "))).toEqual({ ok: false, reason: "unset" });
    expect(ownerConfig(env("a@example.com,b@example.com"))).toEqual({ ok: false, reason: "not_exactly_one" });
    expect(isOwnerEmail("a@example.com", env("a@example.com,b@example.com"))).toBe(false);
    expect(ownerConfig(env("not-an-email"))).toEqual({ ok: false, reason: "invalid" });
    expect(ownerConfig(env("pro@modelroom.test"))).toEqual({ ok: false, reason: "test_account" });
    expect(isOwnerEmail("pro@modelroom.test", env("pro@modelroom.test"))).toBe(false);
    expect(isOwnerEmail(null, env("owner@example.com"))).toBe(false);
    expect(isOwnerEmail("", env("owner@example.com"))).toBe(false);
  });

  it("never opens in production, even for the owner", () => {
    process.env.VERCEL_ENV = "production";
    expect(ownerConfig(env("owner@example.com"))).toEqual({ ok: false, reason: "production" });
    expect(isOwnerEmail("owner@example.com", env("owner@example.com"))).toBe(false);
    delete process.env.VERCEL_ENV;
    process.env.MODELROOM_ENV = "production";
    expect(isOwnerEmail("owner@example.com", env("owner@example.com"))).toBe(false);
  });

  it("ignores the local stand-in session outside `next dev` and on Vercel", () => {
    process.env.MODELROOM_DEV_SESSION_EMAIL = "owner@example.com";
    expect(devSessionEmail()).toBeNull(); // vitest runs with NODE_ENV=test
    process.env.VERCEL = "1";
    expect(devSessionEmail()).toBeNull();
  });

  it("covers the page and its sub-paths only", () => {
    expect(isOwnerPath("/owner")).toBe(true);
    expect(isOwnerPath("/owner/anything")).toBe(true);
    expect(isOwnerPath("/ownership")).toBe(false);
    expect(isOwnerPath("/props")).toBe(false);
  });
});
