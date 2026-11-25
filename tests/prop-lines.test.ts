/** NBA points sportsbook lines (TEST): headline from a stored line, never estimated; SigV4 signing; off in production. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { gridAtLeast, headlineFor } from "@/components/league/simple";
import type { ExplorerRow } from "@/server/data/explorer";

vi.mock("server-only", () => ({}));

const grid = { k0: 10, step: 1, p: Array.from({ length: 31 }, (_, i) => Math.max(0.01, 0.99 - i * 0.03)) }; // P(pts >= 10+i)
const book = { title: "Book A", book: "a", line: 24.5, over: -115, under: -105, over_novig: 0.51, last_update: "2026-11-25T20:39:00Z" };
const row = (over: Partial<ExplorerRow>): ExplorerRow =>
  ({ id: "p1", gameId: "g1", mean: 26, median: 26, range80: [18, 34], support: "ok", supportNote: "", headline: null, ladder: [], lines: [], grid,
     bookLines: null, ...over }) as unknown as ExplorerRow;

describe("stored sportsbook points line", () => {
  it("leads with the consensus line and reads the model at it (more than 24.5 = P(points >= 25))", () => {
    const h = headlineFor(row({ bookLines: { name: "X", books: [book], alternates: 1, consensus_line: 24.5, consensus_over_novig: 0.51, last_update: book.last_update, capturedAt: "2026-11-25T20:40:00Z" } }))!;
    expect(h.fromMarket).toBe(true);
    expect(h.threshold).toBe(24.5);
    expect(h.thresholdText).toBe("more than 24.5");
    expect(h.prob).toBeCloseTo(grid.p[15]);
    expect(h.marketProb).toBe(0.51);
    expect(h.book!.books[0].title).toBe("Book A");
  });
  it("without a stored line, or outside the model's grid, never invents one", () => {
    expect(headlineFor(row({}))?.fromMarket ?? false).toBe(false);
    const far = headlineFor(row({ bookLines: { name: "X", books: [book], alternates: 0, consensus_line: 80.5, consensus_over_novig: 0.5, last_update: null, capturedAt: "t" } }));
    expect(far?.fromMarket ?? false).toBe(false);
    expect(gridAtLeast(grid, 9)).toBeNull();
    expect(gridAtLeast(null, 20)).toBeNull();
  });
});

describe("R2 read (server only)", () => {
  afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });
  it("signs a GET with SigV4 for region auto, without putting the secret in the request", async () => {
    const { signedGet } = await import("@/server/markets/propLines");
    const s = { account: "a".repeat(32), bucket: "model-room-test-archive", key: "AKIDEXAMPLE", secret: "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY" };
    const r = signedGet(s, "v1/market-snapshots/nba/player-points/2026-11-25/latest.json", new Date("2026-11-25T20:40:00Z"));
    expect(r.url).toBe(`https://${"a".repeat(32)}.r2.cloudflarestorage.com/model-room-test-archive/v1/market-snapshots/nba/player-points/2026-11-25/latest.json`);
    expect(r.headers["x-amz-date"]).toBe("20261125T204000Z");
    expect(r.headers.Authorization).toMatch(/^AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE\/20261125\/auto\/s3\/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=[0-9a-f]{64}$/);
    expect(JSON.stringify(r)).not.toContain(s.secret);
  });
  it("is off in production and without the read-only settings", async () => {
    vi.stubEnv("R2_ACCOUNT_ID", "x"); vi.stubEnv("R2_BUCKET", "b"); vi.stubEnv("R2_READ_ACCESS_KEY_ID", "k"); vi.stubEnv("R2_READ_SECRET_ACCESS_KEY", "s");
    vi.stubEnv("VERCEL_ENV", "production");
    let m = await import("@/server/markets/propLines");
    expect(m.propLinesEnabled()).toBe(false);
    expect(await m.loadPropLines("2026-11-25")).toBeNull();
    vi.resetModules(); vi.stubEnv("VERCEL_ENV", "preview"); vi.stubEnv("R2_READ_SECRET_ACCESS_KEY", "");
    m = await import("@/server/markets/propLines");
    expect(m.propLinesEnabled()).toBe(false);
  });
});
