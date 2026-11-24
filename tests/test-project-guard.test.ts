import { describe, expect, it } from "vitest";
import { checkTestProject, fingerprint, refFromDbUrl, refFromUrl } from "../scripts/test-project-guard.mjs";

const A = "abcdefghijklmnopqrst", B = "zyxwvutsrqponmlkjihg";
const fpA = fingerprint(A);

describe("TEST-project guard for setup and test-account scripts", () => {
  it("passes only when every connection is the expected project", () => {
    expect(checkTestProject({ url: `https://${A}.supabase.co`, dbUrl: `postgresql://postgres.${A}:pw@aws-0-us-west-1.pooler.supabase.com:5432/postgres`, expected: fpA })).toEqual([]);
    expect(checkTestProject({ url: `https://${B}.supabase.co`, expected: fpA })[0]).toContain("NOT the TEST project");
    expect(checkTestProject({ url: `https://${A}.supabase.co`, dbUrl: `postgresql://postgres.${B}:pw@host:5432/postgres`, expected: fpA })[0]).toContain("SUPABASE_DB_URL");
    expect(checkTestProject({ expected: fpA })).toEqual(["no Supabase connection given"]);
    expect(checkTestProject({ url: "https://example.com", expected: fpA })[0]).toContain("not a https://<ref>.supabase.co");
  });
  it("problems never contain the URL, password or reference", () => {
    const msg = checkTestProject({ url: `https://${B}.supabase.co`, dbUrl: `postgresql://postgres.${B}:s3cret@host/postgres`, expected: fpA }).join(" ");
    for (const leak of [B, "s3cret", "supabase.co/"]) expect(msg).not.toContain(leak);
  });
  it("reads project references from both URL shapes", () => {
    expect(refFromUrl(`https://${A}.supabase.co`)).toBe(A);
    expect(refFromDbUrl(`postgresql://postgres:pw@db.${A}.supabase.co:5432/postgres`)).toBe(A);
    expect(fpA).toMatch(/^[0-9a-f]{8}$/);
  });
});
