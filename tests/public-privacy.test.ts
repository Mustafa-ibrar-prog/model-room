import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/** Subscriber-facing code never reads book-level market data; it lives only in the owner dashboard. */
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}
const OWNER = ["src/app/owner/", "src/components/owner/", "src/server/owner/"];
const BOOKS = /\b(draftkings|fanduel|betmgm|caesars|williamhill_us|bovada|betrivers|betonlineag|mybookieag|lowvig|betus|fanatics|espnbet|hardrockbet|fliff|ballybet|betparx)\b/i;

describe("public pages and assets carry no sportsbook-level data", () => {
  const src = files("src").map((f) => f.split(path.sep).join("/")).filter((f) => /\.(ts|tsx)$/.test(f));

  it("no subscriber-facing code reads per-book market blocks", () => {
    const hits = src.filter((f) => !OWNER.some((o) => f.startsWith(o))).filter((f) => /by_book|byBook|movement_by_book|line_histories/.test(readFileSync(f, "utf8")));
    expect(hits).toEqual([]);
  });

  it("no sportsbook name is hard-coded outside the owner dashboard", () => {
    const hits = src.filter((f) => !OWNER.some((o) => f.startsWith(o))).filter((f) => BOOKS.test(readFileSync(f, "utf8")));
    expect(hits).toEqual([]);
  });

  it("no static asset in public/ names a sportsbook", () => {
    const pub = files("public").filter((f) => /\.(json|txt|csv|html|svg|js)$/.test(f));
    expect(pub.filter((f) => BOOKS.test(readFileSync(f, "utf8")))).toEqual([]);
  });
});
