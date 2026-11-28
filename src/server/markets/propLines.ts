import "server-only";
import { createHash, createHmac } from "node:crypto";
import { isProduction } from "@/lib/auth-config";

/**
 * NBA player points lines (TEST, Moose 2026-11-24): the latest snapshot The Odds API returned, read server-side from the
 * private R2 bucket with the READ-ONLY token (R2_ACCOUNT_ID, R2_BUCKET, R2_READ_ACCESS_KEY_ID, R2_READ_SECRET_ACCESS_KEY:
 * server environment variables, never NEXT_PUBLIC_, never sent to the browser). Two small reads per cache miss: the
 * day's latest.json pointer, then that day's view. Cached for 10 minutes. Off in production. Returns null when anything
 * is missing: the cards then say "no sportsbook line"; nothing is estimated.
 */
export type BookLine = { book: string; title: string; line: number; over: number | null; under: number | null; over_novig: number | null; last_update: string | null };
export type PlayerBookLines = { name: string; books: BookLine[]; alternates: number; consensus_line: number | null; consensus_over_novig: number | null; last_update: string | null };
export type GameBookLines = { game_id: string | null; captured_at: string; players: Record<string, PlayerBookLines>; unmatched_players: number };
export type DayView = { date: string; updated_at: string | null; games: Record<string, GameBookLines>;
  game_status?: Record<string, { status: "captured" | "empty" | "skipped_cap" | "error"; mode?: string; at?: string | null }> };

const PREFIX = "v1/market-snapshots/nba/player-points";
/** NFL receiving yards (TEST, Moose 2026-11-27): same layout, own prefix. */
export const NFL_PREFIX = "v1/market-snapshots/nfl/player-reception-yds";
const TTL_MS = 10 * 60 * 1000;
const cache = new Map<string, { at: number; view: DayView | null }>();

function settings() {
  const e = process.env;
  const s = { account: e.R2_ACCOUNT_ID?.trim(), bucket: e.R2_BUCKET?.trim(), key: e.R2_READ_ACCESS_KEY_ID?.trim(), secret: e.R2_READ_SECRET_ACCESS_KEY?.trim() };
  return s.account && s.bucket && s.key && s.secret ? (s as { account: string; bucket: string; key: string; secret: string }) : null;
}

export function propLinesEnabled(): boolean {
  return !isProduction() && settings() !== null;
}

const sha = (x: string | Buffer) => createHash("sha256").update(x).digest("hex");
const hmac = (k: Buffer | string, x: string) => createHmac("sha256", k).update(x).digest();

/** AWS Signature V4 GET for one object on R2's S3 endpoint (region "auto"). Exported for tests. */
export function signedGet(s: { account: string; bucket: string; key: string; secret: string }, objectKey: string, now = new Date()) {
  const host = `${s.account}.r2.cloudflarestorage.com`;
  const path = `/${s.bucket}/${objectKey.split("/").map(encodeURIComponent).join("/")}`;
  const amz = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const day = amz.slice(0, 8);
  const payload = sha("");
  const canonical = ["GET", path, "", `host:${host}`, `x-amz-content-sha256:${payload}`, `x-amz-date:${amz}`, "", "host;x-amz-content-sha256;x-amz-date", payload].join("\n");
  const scope = `${day}/auto/s3/aws4_request`;
  const toSign = ["AWS4-HMAC-SHA256", amz, scope, sha(canonical)].join("\n");
  const kSign = hmac(hmac(hmac(hmac(`AWS4${s.secret}`, day), "auto"), "s3"), "aws4_request");
  const sig = createHmac("sha256", kSign).update(toSign).digest("hex");
  return {
    url: `https://${host}${path}`,
    headers: {
      "x-amz-date": amz,
      "x-amz-content-sha256": payload,
      Authorization: `AWS4-HMAC-SHA256 Credential=${s.key}/${scope}, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=${sig}`,
    },
  };
}

async function getObject(s: NonNullable<ReturnType<typeof settings>>, key: string): Promise<Buffer | null> {
  const r = signedGet(s, key);
  const res = await fetch(r.url, { headers: r.headers, cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!res.ok) return null;
  return Buffer.from(await res.arrayBuffer());
}

/** The day's view (Pacific game date), verified against the SHA-256 in latest.json; null when unavailable. */
export async function loadPropLines(date: string, prefix: string = PREFIX): Promise<DayView | null> {
  const s = settings();
  if (!s || isProduction()) return null;
  const ck = `${prefix}|${date}`;
  const hit = cache.get(ck);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.view;
  let view: DayView | null = null;
  try {
    const p = await getObject(s, `${prefix}/${date}/latest.json`);
    if (p) {
      const ptr = JSON.parse(p.toString("utf8")) as { view: string; view_sha256: string };
      const v = await getObject(s, ptr.view);
      if (v && sha(v) === ptr.view_sha256) view = JSON.parse(v.toString("utf8")) as DayView;
    }
  } catch {
    view = null;
  }
  cache.set(ck, { at: Date.now(), view });
  return view;
}

/** Each sportsbook's own game lines (modelroom/sources/gamelines_r2.py): no API call on read; null when unavailable. */
export type BookGameLines = {
  title: string;
  spread?: { line: number; home: number | null; away: number | null; last_update: string | null };
  total?: { line: number; over: number | null; under: number | null; last_update: string | null };
  moneyline?: { home: number | null; away: number | null; last_update: string | null };
};
export type GameLinesView = { league: string; generated_at: string; games: Record<string, { commence_time: string; collected_at: string | null; books: Record<string, BookGameLines> }> };
const glCache = new Map<string, { at: number; view: GameLinesView | null }>();

export async function loadGameLines(league: "nba" | "nfl"): Promise<GameLinesView | null> {
  const s = settings();
  if (!s || isProduction()) return null;
  const hit = glCache.get(league);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.view;
  let view: GameLinesView | null = null;
  try {
    const p = await getObject(s, `v1/market-snapshots/${league}/game-lines/latest.json`);
    if (p) {
      const ptr = JSON.parse(p.toString("utf8")) as { view: string; view_sha256: string };
      const v = await getObject(s, ptr.view);
      if (v && sha(v) === ptr.view_sha256) view = JSON.parse(v.toString("utf8")) as GameLinesView;
    }
  } catch {
    view = null;
  }
  glCache.set(league, { at: Date.now(), view });
  return view;
}

/** Pacific calendar date of a game start (the snapshot folder's date). */
export function ptDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
}
