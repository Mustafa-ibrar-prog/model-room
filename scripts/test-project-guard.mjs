// Refuses to continue unless every Supabase connection points at the TEST project (vrku…).
// Compares sha256 fingerprints (first 8 hex characters of the project reference), never prints a URL, key or the
// reference itself. The expected fingerprint is not a secret (the Supabase checks print it); if the TEST site ever
// moves to a new project, set the repository VARIABLE MODELROOM_TEST_PROJECT_FP to the new fingerprint.
//
//   node scripts/test-project-guard.mjs        checks SUPABASE_URL and SUPABASE_DB_URL (whichever are set)
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

export const DEFAULT_TEST_PROJECT_FP = "680cbd6c";

export const fingerprint = (ref) => createHash("sha256").update(ref).digest("hex").slice(0, 8);

export function refFromUrl(u) {
  return /^https:\/\/([a-z0-9]{20})\.supabase\.co\/?$/.exec(u ?? "")?.[1] ?? null;
}

export function refFromDbUrl(u) {
  return (/postgres\.([a-z0-9]{20})[:@]/.exec(u ?? "") ?? /db\.([a-z0-9]{20})\.supabase\.co/.exec(u ?? ""))?.[1] ?? null;
}

/**
 * Returns a list of problems (empty = every provided connection is the TEST project).
 * @param {{ url?: string, dbUrl?: string, expected?: string }} opts
 */
export function checkTestProject({ url, dbUrl, expected = DEFAULT_TEST_PROJECT_FP }) {
  const problems = [];
  if (!url && !dbUrl) problems.push("no Supabase connection given");
  if (url) {
    const r = refFromUrl(url);
    if (!r) problems.push("SUPABASE_URL is not a https://<ref>.supabase.co project URL");
    else if (fingerprint(r) !== expected) problems.push("SUPABASE_URL points at a project that is NOT the TEST project");
  }
  if (dbUrl) {
    const r = refFromDbUrl(dbUrl);
    if (!r) problems.push("SUPABASE_DB_URL has no recognisable project reference");
    else if (fingerprint(r) !== expected) problems.push("SUPABASE_DB_URL points at a project that is NOT the TEST project");
  }
  return problems;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const expected = (process.env.MODELROOM_TEST_PROJECT_FP || DEFAULT_TEST_PROJECT_FP).trim();
  const problems = checkTestProject({ url: process.env.SUPABASE_URL, dbUrl: process.env.SUPABASE_DB_URL, expected });
  if (problems.length) {
    for (const p of problems) console.log(`FAIL  ${p}`);
    console.log("Refusing: test-account and setup steps only ever run against the TEST Supabase project.");
    process.exit(1);
  }
  console.log(`ok    every Supabase connection is the TEST project (fingerprint ${expected})`);
}
