import "server-only";
import postgres from "postgres";
import { requireOwner } from "./access";

/**
 * The owner dashboard's only database connection: MODELROOM_OWNER_DB_URL (a server-only Vercel TEST variable) for
 * the read-only `owner_reader` role (supabase/migrations/20261112000100_owner_reader.sql), which can SELECT
 * odds.snapshots, odds.comparisons, odds.reports and scheduler.health and nothing else. Every query also runs
 * inside a READ ONLY transaction, so a misconfigured role still cannot write.
 *
 * Missing or unreachable credentials never fall back to anything: callers get { ok: false } and the page shows
 * an "unavailable" state. Error details (which could contain a host name) are never sent to the page.
 */
export type DbResult<T> = { ok: true; data: T } | { ok: false; reason: "not_configured" | "unreachable" };

type Sql = ReturnType<typeof postgres>;
let client: Sql | null = null;

export const ownerDbConfigured = () => Boolean(process.env.MODELROOM_OWNER_DB_URL);

function local(url: string): boolean {
  return /@(localhost|127\.0\.0\.1)[:/]/.test(url) || /[?&]host=\//.test(url) || /@\/[^?]/.test(url);
}

function sql(): Sql {
  if (!client) {
    const url = process.env.MODELROOM_OWNER_DB_URL!;
    client = postgres(url, {
      max: 2,
      idle_timeout: 20,
      connect_timeout: 8,
      prepare: false, // the Supabase transaction pooler does not keep prepared statements
      ssl: local(url) ? false : "require",
      connection: { application_name: "modelroom-owner-dashboard" },
      onnotice: () => {},
    });
  }
  return client;
}

export async function ownerQuery<T>(fn: (tx: postgres.TransactionSql) => Promise<T>): Promise<DbResult<T>> {
  await requireOwner();
  if (!ownerDbConfigured()) return { ok: false, reason: "not_configured" };
  try {
    const data = (await sql().begin("read only", (tx) => fn(tx))) as T;
    return { ok: true, data };
  } catch (e) {
    console.error("owner dashboard: database query failed", (e as { code?: string }).code ?? "no code");
    return { ok: false, reason: "unreachable" };
  }
}
