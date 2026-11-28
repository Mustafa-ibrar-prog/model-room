import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { isProduction } from "@/lib/auth-config";

/**
 * TEST private view for the Parlay Builder (Moose 2026-11-27). Polymarket US prices may only be used as PMUS permits, so
 * they are shown to the site owner only, never to other TEST visitors, and never outside TEST. Logins are switched off
 * on TEST, so the owner unlocks the view with a key he sets himself as the server variable MODELROOM_PRIVATE_VIEW_KEY in
 * Vercel (Preview). The browser keeps only an HMAC of it in an httpOnly cookie; the key is never sent back or logged.
 */
export const PRIVATE_COOKIE = "mr_pv";
const MIN_KEY = 16;

const key = () => {
  const k = process.env.MODELROOM_PRIVATE_VIEW_KEY?.trim();
  return k && k.length >= MIN_KEY ? k : null;
};
export const privateKeyConfigured = () => !isProduction() && key() !== null;
export const privateToken = (k: string) => createHmac("sha256", k).update("model-room-private-view-v1").digest("hex");

function same(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** True when this request carries the owner cookie (TEST only). */
export function isPrivateViewer(cookieValue: string | undefined | null): boolean {
  const k = key();
  if (isProduction() || !k || !cookieValue) return false;
  return same(cookieValue, privateToken(k));
}

/** Checks a typed key; returns the cookie value to set, or null. */
export function unlock(typed: unknown): string | null {
  const k = key();
  if (isProduction() || !k || typeof typed !== "string" || typed.length > 200) return null;
  return same(typed.trim(), k) ? privateToken(k) : null;
}

const attempts = new Map<string, { n: number; at: number }>();
/** At most 10 tries an hour per network address. */
export function allowAttempt(net: string, now = Date.now()): boolean {
  const a = attempts.get(net);
  if (!a || now - a.at > 3600_000) {
    attempts.set(net, { n: 1, at: now });
    return true;
  }
  a.n++;
  return a.n <= 10;
}
