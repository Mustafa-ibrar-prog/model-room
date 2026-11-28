import "server-only";
import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { isProduction } from "@/lib/auth-config";
import type { League } from "@/types/domain";
import { hash } from "@/server/ai/limits";
import { getCatalog, type Catalog } from "./legs";
import { MAX_LEGS } from "./price";

/** Shared plumbing for the Parlay Builder API routes (TEST only: every route answers 404 in production). */
export const parlayEnabled = () => !isProduction();
export const notFound = () => NextResponse.json({ error: "Not found." }, { status: 404 });
export const noStore = { "Cache-Control": "private, no-store" };

const ID_RE = /^(nba|nfl)~[A-Za-z0-9_]{1,40}~(prop|spread|total|ml)~[A-Za-z0-9_.+-]{1,40}(~[A-Za-z0-9_.+-]{1,40}){0,3}$/;

export async function readLegIds(req: NextRequest): Promise<string[] | null> {
  const text = await req.text();
  if (text.length > 4000) return null;
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return null;
  }
  const legs = (body as { legs?: unknown })?.legs;
  if (!Array.isArray(legs) || legs.length === 0 || legs.length > MAX_LEGS) return null;
  if (!legs.every((x) => typeof x === "string" && ID_RE.test(x))) return null;
  return legs as string[];
}

export async function catalogsFor(ids: string[], now = new Date(), live = false): Promise<Catalog[]> {
  const leagues = [...new Set(ids.map((i) => i.split("~")[0] as League))];
  return Promise.all(leagues.map((l) => getCatalog(l, now, { live })));
}

export const leagueParam = (v: string | null): League | null => (v === "nba" || v === "nfl" ? v : null);

/** Anonymous visitor id (random, httpOnly cookie) and a hashed network address, for per-visitor caps only. */
export function visitor(req: NextRequest): { id: string; net: string; fresh: boolean } {
  const c = req.cookies.get("mr_aid")?.value;
  const ok = c && /^[a-f0-9-]{36}$/.test(c);
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  return { id: ok ? c! : randomUUID(), net: hash(`net:${ip}`).slice(0, 24), fresh: !ok };
}

export function withVisitor(res: NextResponse, v: { id: string; fresh: boolean }) {
  if (v.fresh) res.cookies.set("mr_aid", v.id, { httpOnly: true, sameSite: "lax", secure: true, path: "/api/parlay", maxAge: 60 * 60 * 24 * 30 });
  return res;
}
