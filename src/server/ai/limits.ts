import "server-only";
import { createHash } from "node:crypto";

/**
 * Caching and request caps for Gemini (TEST, Moose 2026-11-27).
 *   cache      identical fact packs reuse the stored answer for 6 hours (no new request; doesn't count against caps)
 *   per user   GEMINI_USER_DAILY (default 8) per visitor id per Pacific day, and 3x that per network address
 *   site-wide  GEMINI_SITE_DAILY (default 150) per server instance per Pacific day
 * Counters live in server memory: they reset when an instance restarts and each instance counts separately. Google's
 * own free-tier quota is the hard stop behind them (a 429 pauses AI until Pacific midnight; nothing is ever billed).
 */
const CACHE_TTL_MS = 6 * 3600_000;
const CACHE_MAX = 300;

const cache = new Map<string, { at: number; value: unknown }>();
const counts = new Map<string, number>();
let day = "";

export const hash = (x: string) => createHash("sha256").update(x).digest("hex");

function pacificDay(now: Date) {
  return now.toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
}

function roll(now: Date) {
  const d = pacificDay(now);
  if (d !== day) {
    day = d;
    counts.clear();
  }
}

export function cacheGet<T>(key: string, now = Date.now()): T | null {
  const hit = cache.get(key);
  if (!hit) return null;
  if (now - hit.at > CACHE_TTL_MS) {
    cache.delete(key);
    return null;
  }
  return hit.value as T;
}

export function cacheSet(key: string, value: unknown, now = Date.now()) {
  if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value!);
  cache.set(key, { at: now, value });
}

const num = (v: string | undefined, d: number) => (v && /^\d+$/.test(v) ? Number(v) : d);
export const limits = () => ({ user: num(process.env.GEMINI_USER_DAILY, 8), site: num(process.env.GEMINI_SITE_DAILY, 150) });

export type CapCheck = { ok: true } | { ok: false; scope: "user" | "site"; message: string };

/** Checks and, when allowed, records one request. `who` = visitor id; `net` = hashed network address. */
export function takeQuota(who: string, net: string, now = new Date()): CapCheck {
  roll(now);
  const L = limits();
  const site = counts.get("site") ?? 0;
  if (site >= L.site) return { ok: false, scope: "site", message: "The site's AI allowance for today is used up. It resets at midnight Pacific; the numbers still work." };
  const u = counts.get(`u:${who}`) ?? 0;
  const n = counts.get(`n:${net}`) ?? 0;
  if (u >= L.user || n >= L.user * 3) return { ok: false, scope: "user", message: `You've used today's ${L.user} AI explanations. They reset at midnight Pacific; the numbers still work.` };
  counts.set("site", site + 1);
  counts.set(`u:${who}`, u + 1);
  counts.set(`n:${net}`, n + 1);
  return { ok: true };
}

export function usage(who: string, now = new Date()) {
  roll(now);
  const L = limits();
  return { used: counts.get(`u:${who}`) ?? 0, limit: L.user };
}

export function resetForTests() {
  cache.clear();
  counts.clear();
  day = "";
}
