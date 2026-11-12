import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/** Owner-only modules may be imported only by the owner page, its components, and the request proxy. */
const ALLOWED = ["src/app/owner/", "src/components/owner/", "src/server/owner/", "src/proxy.ts"];
const OWNER_IMPORT = /from\s+["'](@\/server\/owner\/[^"']+|@\/components\/owner\/[^"']+|\.\.?\/(?:[^"']*\/)?owner\/[^"']+)["']/g;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(f) ? [p] : [];
  });
}

describe("owner dashboard isolation", () => {
  it("owner modules are imported only by the owner page, its components and the proxy", () => {
    const offenders = files("src")
      .map((f) => f.split(path.sep).join("/"))
      .filter((f) => !ALLOWED.some((a) => f.startsWith(a) || f === a))
      .flatMap((f) => [...readFileSync(f, "utf8").matchAll(OWNER_IMPORT)].map((m) => `${f} imports ${m[1]}`));
    expect(offenders).toEqual([]);
  });

  it("the owner page has no client components and no API route", () => {
    const owner = [...files("src/app/owner"), ...files("src/components/owner"), ...files("src/server/owner")];
    expect(owner.filter((f) => /^\s*["']use client["']/m.test(readFileSync(f, "utf8")))).toEqual([]);
    expect(files("src/app/api").filter((f) => /owner/i.test(readFileSync(f, "utf8")))).toEqual([]);
  });

  it("the database connection string is read only on the server and never as a public variable", () => {
    const all = files("src").map((f) => [f, readFileSync(f, "utf8")] as const);
    expect(all.filter(([, t]) => /NEXT_PUBLIC_[A-Z_]*OWNER|NEXT_PUBLIC_[A-Z_]*DB_URL/.test(t)).map(([f]) => f)).toEqual([]);
    expect(all.filter(([, t]) => t.includes("MODELROOM_OWNER_DB_URL")).map(([f]) => f.split(path.sep).join("/"))).toEqual(
      expect.arrayContaining(["src/server/owner/db.ts"]),
    );
    const db = readFileSync("src/server/owner/db.ts", "utf8");
    expect(db.startsWith('import "server-only";')).toBe(true);
    expect(db).toContain('begin("read only"');
  });
});
