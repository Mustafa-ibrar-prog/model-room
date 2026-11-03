// End-to-end check of logins and plan access on the TEST SITE, in a real browser.
//
//   PREVIEW_URL=https://… TEST_ACCOUNT_PASSWORD=… node e2e/preview-accounts.mjs
//
// For each test account: log in, check the Account menu shows the right plan, check what the server
// sends for Free / Plus / Pro features, log out. Also checks an anonymous visitor can browse, and that
// the old plan-switcher cookie can't grant a plan once logins are on. Prints no secrets.
import { chromium } from "playwright";

const BASE = (process.env.PREVIEW_URL ?? "").replace(/\/$/, "");
const PASSWORD = process.env.TEST_ACCOUNT_PASSWORD;
if (!BASE || !PASSWORD) { console.log("FAIL  PREVIEW_URL and TEST_ACCOUNT_PASSWORD are required"); process.exit(1); }
if (!/vercel\.app$/.test(new URL(BASE).hostname) || /^model-room\.vercel\.app$/.test(new URL(BASE).hostname)) {
  console.log("FAIL  refusing to run against anything but a preview deployment"); process.exit(1);
}

let failed = 0;
const ok = (m) => console.log(`ok    ${m}`);
const bad = (m) => { failed++; console.log(`FAIL  ${m}`); };
const check = (cond, m) => (cond ? ok(m) : bad(m));

const LOCK_PROPS = "Player props are part of Plus";
const LOCK_INPUTS = "Model inputs (usage, matchup factors) are part of Pro.";
const LOCK_HISTORY = "Prop results are on Pro";

const browser = await chromium.launch();

async function text(page, path) {
  const r = await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 60000 });
  return { status: r?.status() ?? 0, body: await page.locator("body").innerText() };
}

async function propsCheck(page, tier, who) {
  const { status, body } = await text(page, "/props?sport=nfl");
  if (status !== 200) return bad(`${who}: /props returned HTTP ${status}`);
  const noGames = body.includes("No upcoming games");
  if (tier === "free") {
    check(body.includes(LOCK_PROPS) || noGames, `${who}: player props locked (Plus required)`);
    check((await page.locator('section[aria-label="Model Room projection"]').count()) === 0, `${who}: no player projections sent to the page`);
  } else if (!noGames) {
    check(!body.includes(LOCK_PROPS) && (await page.locator('section[aria-label="Model Room projection"]').count()) > 0, `${who}: player projections shown`);
    const inputsLocked = (await page.locator(`text=${LOCK_INPUTS}`).count()) > 0;
    check(tier === "plus" ? inputsLocked : !inputsLocked, `${who}: model inputs ${tier === "plus" ? "locked (Pro only)" : "available"}`);
  } else ok(`${who}: no NFL games in the props window to check`);
  const hist = await text(page, "/props?sport=nfl&date=2026-11-01");
  const histLocked = hist.body.includes(LOCK_HISTORY);
  check(tier === "pro" ? !histLocked : histLocked || hist.body.includes("No NFL games"), `${who}: prop results history ${tier === "pro" ? "available" : "locked (Pro only)"}`);
}

// 1. Anonymous visitor.
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const home = await text(page, "/");
  if (home.status === 401 || /vercel\.com\/login|Log in to Vercel/i.test(home.body)) {
    bad("the test site asks for a Vercel login: turn off Vercel Authentication (Settings → Deployment Protection)");
    await browser.close(); process.exit(1);
  }
  check(home.status === 200, "home page loads without an account");
  check((await page.locator("header >> text=Log in").count()) > 0 && (await page.locator("header >> text=Sign up").count()) > 0, "header shows Log in and Sign up");
  const nfl = await text(page, "/nfl");
  check(nfl.status === 200 && !page.url().includes("/login"), "anonymous visitor can browse /nfl");
  await propsCheck(page, "free", "anonymous");
  // The old test-site plan switcher must not work once logins are on.
  await ctx.addCookies([{ name: "mr_preview_tier", value: "pro", url: BASE }]);
  const forged = await text(page, "/props?sport=nfl");
  check(forged.body.includes(LOCK_PROPS) || forged.body.includes("No upcoming games"), "a forged plan cookie doesn't unlock anything (plans come from the server)");
  const login = await text(page, "/login");
  check(login.body.includes("Log in") && (await page.locator('input[name="email"]').count()) === 1, "login page has the form");
  check((await text(page, "/signup")).body.includes("Create an account"), "signup page loads");
  check((await text(page, "/forgot-password")).status === 200, "password reset page loads");
  await ctx.close();
}

// 2. Each test account.
for (const [email, tier] of [["free-test@modelroom.test", "free"], ["plus-test@modelroom.test", "plus"], ["pro-test@modelroom.test", "pro"]]) {
  const who = email.split("@")[0];
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', PASSWORD);
  await Promise.all([page.waitForURL(/\/account/, { timeout: 30000 }).catch(() => null), page.click('form button[type="submit"]')]);
  if (!page.url().includes("/account")) {
    const msg = await page.locator("[role=alert]").first().innerText().catch(() => "no message");
    bad(`${who}: login did not reach /account (${msg})`);
    await ctx.close();
    continue;
  }
  ok(`${who}: logged in`);
  const acct = await page.locator("main").innerText();
  const name = { free: "Free", plus: "Plus", pro: "Pro" }[tier];
  const plan = (await page.locator("main dd.font-display").first().innerText().catch(() => "")).trim();
  check(acct.includes(email) && plan.toLowerCase() === tier, `${who}: account page shows ${name} (got ${plan || "nothing"})`);
  const setup = await page.locator('[data-testid="setup-check"]').innerText().catch(() => null);
  if (setup) console.log(`info  ${who}: ${setup}`);
  const menu = page.locator("header details summary").first();
  check((await menu.count()) > 0 && (await menu.innerText()).toLowerCase().includes(tier), `${who}: header Account menu shows ${name}`);
  await propsCheck(page, tier, who);
  // Pricing reflects the plan.
  const pricing = await text(page, "/pricing");
  check(pricing.body.includes("Your plan"), `${who}: pricing marks the current plan`);
  // Log out from the menu.
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.locator("header details summary").first().click();
  await page.locator("header details button:has-text('Log out')").click();
  const out = await page.locator("header >> text=Log in").first().waitFor({ timeout: 20000 }).then(() => true).catch(() => false);
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  check(out && (await page.locator("header >> text=Log in").count()) > 0 && (await page.locator("header details").count()) === 0, `${who}: logged out`);
  const after = await text(page, "/props?sport=nfl");
  check(after.body.includes(LOCK_PROPS) || after.body.includes("No upcoming games"), `${who}: after logout, Plus features are locked again`);
  await ctx.close();
}

await browser.close();
if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log("all checks passed");
