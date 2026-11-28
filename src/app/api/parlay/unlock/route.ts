import { NextResponse, type NextRequest } from "next/server";
import { allowAttempt, PRIVATE_COOKIE, privateKeyConfigured, unlock } from "@/server/parlay/privateView";
import { noStore, notFound, parlayEnabled, visitor } from "@/server/parlay/request";

/** POST {key}: unlock the TEST private view (live Polymarket US prices). DELETE: lock it again. */
export async function POST(req: NextRequest) {
  if (!parlayEnabled() || !privateKeyConfigured()) return notFound();
  const v = visitor(req);
  if (!allowAttempt(v.net)) return NextResponse.json({ error: "Too many tries. Wait an hour." }, { status: 429, headers: noStore });
  let body: unknown = null;
  try {
    body = JSON.parse((await req.text()).slice(0, 500));
  } catch {
    body = null;
  }
  const token = unlock((body as { key?: unknown } | null)?.key);
  if (!token) return NextResponse.json({ error: "That key doesn't match." }, { status: 403, headers: noStore });
  const res = NextResponse.json({ ok: true }, { headers: noStore });
  res.cookies.set(PRIVATE_COOKIE, token, { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: 60 * 60 * 24 * 30 });
  return res;
}

export async function DELETE() {
  if (!parlayEnabled()) return notFound();
  const res = NextResponse.json({ ok: true }, { headers: noStore });
  res.cookies.set(PRIVATE_COOKIE, "", { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: 0 });
  return res;
}
