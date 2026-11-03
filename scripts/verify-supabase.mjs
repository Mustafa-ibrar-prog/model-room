// Checks the TEST SITE's Supabase setup without printing any secret.
//
//   node scripts/verify-supabase.mjs preflight   key formats, project URL, Auth and database API reachable
//   node scripts/verify-supabase.mjs accounts    each test account signs in, has the right plan, and
//                                                (row-level security is checked in SQL by the workflow)
//
// Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (sb_secret_… or legacy service_role JWT),
//      TEST_ACCOUNT_PASSWORD, MODELROOM_TARGET=preview.
import { createClient } from "@supabase/supabase-js";

const mode = process.argv[2];
const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY: KEY, TEST_ACCOUNT_PASSWORD, MODELROOM_TARGET } = process.env;
let failed = 0;
const ok = (m) => console.log(`ok    ${m}`);
const bad = (m) => { failed++; console.log(`FAIL  ${m}`); };

function keyKind(key) {
  if (!key) return "missing";
  if (key.startsWith("sb_secret_")) return "secret";
  if (key.startsWith("sb_publishable_")) return "publishable";
  const p = key.split(".");
  if (p.length === 3) {
    try {
      const role = JSON.parse(Buffer.from(p[1], "base64url").toString("utf8")).role;
      return role === "service_role" ? "legacy-service" : role === "anon" ? "legacy-anon" : "unknown";
    } catch { /* fall through */ }
  }
  return "unknown";
}

if (MODELROOM_TARGET !== "preview") { console.log("FAIL  MODELROOM_TARGET must be preview"); process.exit(1); }

const kind = keyKind(KEY);
if (kind === "secret") ok("SUPABASE_SERVICE_ROLE_KEY is a new-format secret key (sb_secret_…)");
else if (kind === "legacy-service") ok("SUPABASE_SERVICE_ROLE_KEY is a legacy service_role key");
else bad(`SUPABASE_SERVICE_ROLE_KEY is ${kind === "publishable" || kind === "legacy-anon" ? "a PUBLIC key; it needs the secret key" : kind}`);

let url;
try {
  url = new URL(SUPABASE_URL);
  if (url.protocol === "https:" && /\.supabase\.co$/.test(url.hostname) && (url.pathname === "/" || url.pathname === "")) ok("SUPABASE_URL is a project URL (https://<ref>.supabase.co)");
  else bad("SUPABASE_URL should look like https://<project-ref>.supabase.co with nothing after it");
} catch { bad("SUPABASE_URL isn't a valid URL"); }
if (failed) process.exit(1);
const base = url.origin;

if (mode === "preflight") {
  const h = await fetch(`${base}/auth/v1/health`, { headers: { apikey: KEY } });
  h.ok ? ok("Auth service reachable with this key") : bad(`Auth health returned HTTP ${h.status}`);
  const s = await fetch(`${base}/auth/v1/settings`, { headers: { apikey: KEY } });
  if (s.ok) {
    const j = await s.json();
    j.external?.email ? ok("Email + password sign-in is enabled") : bad("Email provider is disabled (Authentication → Sign In / Providers → Email)");
    console.log(`info  new sign-ups ${j.disable_signup ? "disabled" : "enabled"}; email confirmation ${j.mailer_autoconfirm ? "off (auto-confirm)" : "required"}`);
  } else bad(`Auth settings returned HTTP ${s.status}`);
  const db = createClient(base, KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  const { error } = await db.auth.admin.listUsers({ page: 1, perPage: 1 });
  error ? bad(`Admin API refused the key: ${error.message}`) : ok("Admin API accepts the key (can create users)");
}

if (mode === "accounts") {
  const admin = createClient(base, KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  const want = { "free-test@modelroom.test": "free", "plus-test@modelroom.test": "plus", "pro-test@modelroom.test": "pro" };
  for (const [email, tier] of Object.entries(want)) {
    const c = createClient(base, KEY, { auth: { persistSession: false, autoRefreshToken: false } });
    const { data, error } = await c.auth.signInWithPassword({ email, password: TEST_ACCOUNT_PASSWORD });
    if (error || !data.session) { bad(`${email} can't sign in: ${error?.message ?? "no session"}`); continue; }
    const { data: rows, error: e2 } = await admin.from("memberships").select("tier,status,source").eq("user_id", data.user.id).eq("status", "active");
    if (e2) { bad(`${email}: reading memberships failed: ${e2.message}`); continue; }
    const got = rows.length ? rows.map((r) => r.tier).join(",") : "free";
    got === tier ? ok(`${email} signs in; plan ${tier}`) : bad(`${email} plan is ${got}, expected ${tier}`);
  }
}

if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log("all checks passed");
