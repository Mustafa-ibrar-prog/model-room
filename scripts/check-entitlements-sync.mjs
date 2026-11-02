#!/usr/bin/env node
// Fails if the plan rules in src/lib/entitlements.ts and the tier_features
// seed in the Supabase migrations disagree. Run: npm run check:entitlements
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

// App side: entries like  "games.schedule": "free",  or  watchlists: "plus",
const ts = readFileSync(join(root, "src/lib/entitlements.ts"), "utf8");
const block = ts.match(/MIN_TIER[^=]*=\s*\{([\s\S]*?)\};/);
if (!block) fail("Could not find MIN_TIER in src/lib/entitlements.ts");
const app = new Map(
  [...block[1].matchAll(/["']?([\w.]+)["']?\s*:\s*["'](free|plus|pro)["']/g)].map((m) => [m[1], m[2]]),
);

// Database side: rows like  ('games.schedule', 'free', ...)
const migrationsDir = join(root, "supabase/migrations");
const sql = readdirSync(migrationsDir)
  .filter((f) => f.endsWith(".sql"))
  .sort()
  .map((f) => readFileSync(join(migrationsDir, f), "utf8"))
  .join("\n");
const seed = sql.match(/insert into public\.tier_features[\s\S]*?;/);
if (!seed) fail("Could not find the tier_features insert in supabase/migrations");
const db = new Map([...seed[0].matchAll(/\(\s*'([\w.]+)'\s*,\s*'(free|plus|pro)'/g)].map((m) => [m[1], m[2]]));

const problems = [];
for (const [feature, tier] of app) {
  if (!db.has(feature)) problems.push(`${feature}: in the app (${tier}) but missing from tier_features`);
  else if (db.get(feature) !== tier) problems.push(`${feature}: app says ${tier}, database says ${db.get(feature)}`);
}
for (const feature of db.keys()) {
  if (!app.has(feature)) problems.push(`${feature}: in tier_features but missing from the app`);
}

if (problems.length) fail(`Entitlements out of sync:\n  ${problems.join("\n  ")}`);
console.log(`Entitlements in sync (${app.size} features).`);

function fail(msg) {
  console.error(msg);
  process.exit(1);
}
