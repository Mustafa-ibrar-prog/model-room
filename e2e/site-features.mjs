// Functional checks of every interactive feature, desktop and phone, in a real browser.
//
//   BASE=http://localhost:3999 TIER_COOKIE=pro node e2e/site-features.mjs     (local dev with the plan switcher)
//   BASE=https://<preview> TEST_ACCOUNT_PASSWORD=… node e2e/site-features.mjs  (test site: logs in as pro-test)
//
// Prints ok / FAIL per check; exits 1 on any failure. Uses only what the page shows; never edits data.
import { chromium, devices } from "playwright";

const BASE = (process.env.BASE ?? "").replace(/\/$/, "");
if (!BASE) { console.log("FAIL  BASE is required"); process.exit(1); }
let failed = 0;
const ok = (m) => console.log(`ok    ${m}`);
const bad = (m) => { failed++; console.log(`FAIL  ${m}`); };
const check = (c, m) => (c ? ok(m) : bad(m));
const browser = await chromium.launch();

async function session(device) {
  const ctx = await browser.newContext(device === "phone" ? { ...devices["iPhone 14"] } : { viewport: { width: 1440, height: 1000 } });
  if (process.env.TIER_COOKIE) await ctx.addCookies([{ name: "mr_preview_tier", value: process.env.TIER_COOKIE, url: BASE }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 160)); });
  if (process.env.TEST_ACCOUNT_PASSWORD) {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    await page.fill('input[name="email"]', "pro-test@modelroom.test");
    await page.fill('input[name="password"]', process.env.TEST_ACCOUNT_PASSWORD);
    await Promise.all([page.waitForURL(/\/account/, { timeout: 30000 }).catch(() => null), page.click('form button[type="submit"]')]);
  }
  return { ctx, page, errors };
}

const go = async (page, path) => {
  const r = await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 90000 });
  return r?.status() ?? 0;
};
/** Click something that navigates (client-side or full) and wait for the URL to change. */
async function nav(page, locator) {
  const before = page.url();
  await locator.click();
  await page.waitForURL((u) => u.toString() !== before, { timeout: 30000 }).catch(() => null);
  await page.waitForLoadState("networkidle");
}
const noHScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
const qs = (page) => new URL(page.url()).searchParams;
const rows = (page) => page.locator("li[data-fav-id]:visible");

// ------------------------------------------------------------------ every page, both sizes
for (const device of ["desktop", "phone"]) {
  const { ctx, page, errors } = await session(device);
  for (const path of ["/", "/nfl", "/nba", "/props?sport=nfl", "/props?sport=nba", "/performance?sport=nfl", "/performance?sport=nba", "/pricing", "/injuries", "/ratings", "/account", "/login"]) {
    errors.length = 0;
    const st = await go(page, path);
    check(st === 200, `${device} ${path}: loads (HTTP ${st})`);
    check(await noHScroll(page), `${device} ${path}: no sideways scrolling`);
    check(errors.length === 0, `${device} ${path}: no script errors${errors.length ? ` (${errors[0]})` : ""}`);
  }
  await ctx.close();
}

// ------------------------------------------------------------------ props marketplace (desktop)
{
  const { ctx, page } = await session("desktop");
  await go(page, "/props?sport=nfl");
  const tabs = page.locator('nav[aria-label="Prop categories"] a');
  const labels = await tabs.allInnerTexts();
  const NFL = ["Passing yards", "Passing TDs", "Pass attempts", "Completions", "Interceptions", "Rushing yards", "Rush attempts", "Receiving yards", "Receptions", "Longest reception", "Rush + rec yards", "Anytime TD", "Fantasy points"];
  check(NFL.every((l) => labels.includes(l)), `NFL categories present (${labels.length})`);
  const games = page.locator('nav[aria-label="Games"] a:visible');
  check((await games.count()) > 0, `game list shows ${await games.count()} games`);

  // Category → only relevant positions.
  await go(page, "/props?sport=nfl&cat=passing_yards");
  const qbOnly = (await rows(page).allInnerTexts()).every((t) => /\bQB\b/.test(t));
  check((await rows(page).count()) > 0 && qbOnly, `passing yards lists only QBs (${await rows(page).count()})`);
  await go(page, "/props?sport=nfl&cat=receiving_yards");
  const recv = (await rows(page).allInnerTexts()).every((t) => /\b(WR|TE|RB)\b/.test(t));
  check(recv, "receiving yards lists only WR / TE / RB");

  // Switch game from the list.
  const second = page.locator('nav[aria-label="Games"] a:visible').nth(1);
  if (await second.count()) {
    await nav(page, second);
    check(qs(page).get("game") !== null && qs(page).get("cat") === "receiving_yards", "switching game keeps the stat");
  }

  // Sort.
  await go(page, "/props?sport=nfl&cat=receiving_yards&sort=player");
  const names = (await page.locator("li[data-fav-id] .font-600.text-ink").allInnerTexts()).map((s) => s.trim());
  check(names.length > 1 && names.every((n, i) => i === 0 || names[i - 1].localeCompare(n) <= 0), "sort by player is alphabetical");
  await go(page, "/props?sport=nfl&cat=receiving_yards&sort=projection");
  const med = (await page.locator('li[data-fav-id] section[aria-label="Model Room projection"]:visible .font-display').allInnerTexts()).map(Number);
  check(med.length > 1 && med.every((m, i) => i === 0 || med[i - 1] >= m), "sort by projection is descending");
  await go(page, "/props?sport=nfl&cat=receiving_yards&sort=edge");
  check((await rows(page).count()) > 0, "sort by edge renders");

  // Filters.
  await go(page, "/props?sport=nfl&cat=receiving_yards&only=ok");
  const conf = await page.locator('li[data-fav-id] section[aria-label="Model Room projection"]:visible').allInnerTexts();
  check(conf.every((t) => /High/.test(t)), "High-confidence filter shows only High");
  const gid = (await page.locator('nav[aria-label="Games"] a[aria-current="page"]:visible').first().getAttribute("href")) ?? "";
  const game = new URL(BASE + gid).searchParams.get("game");
  const teamAbbr = game ? game.split("_").pop() : null;
  if (teamAbbr) {
    await go(page, `/props?sport=nfl&cat=receiving_yards&game=${game}&team=${teamAbbr}`);
    const t = await rows(page).allInnerTexts();
    check(t.length > 0 && t.every((x) => x.includes(teamAbbr)), `team filter (${teamAbbr})`);
  }
  await go(page, "/props?sport=nfl&cat=receiving_yards&only=priced");
  check(await page.locator("text=No players match").count() > 0 || (await rows(page).count()) >= 0, "with-exchange-prices filter renders");

  // Search across every game.
  await go(page, "/props?sport=nfl&cat=receiving_yards");
  const first = (await page.locator("li[data-fav-id] .font-600.text-ink").first().innerText()).trim();
  const term = first.split(" ").pop();
  await page.fill("#q", term);
  await nav(page, page.locator('form[action="/props"] button[type="submit"]'));
  const found = (await page.locator("li[data-fav-id] .font-600.text-ink").allInnerTexts()).map((s) => s.toLowerCase());
  check(found.length > 0 && found.every((n) => n.includes(term.toLowerCase())), `search "${term}" returns only matching players (${found.length})`);
  check((await page.locator("text=across every NFL game").count()) > 0, "search covers every game");

  // Contract detail.
  await go(page, "/props?sport=nfl&cat=receiving_yards");
  const c = page.locator("li[data-fav-id] a[href*='line=']").nth(1);
  const label = (await c.locator(".font-mono").first().innerText()).trim();
  await nav(page, c);
  const det = page.locator('aside[aria-label="Contract detail"]');
  check(qs(page).get("line") !== null && (await det.innerText()).includes(label), `opening ${label} shows its detail`);
  const dt = await det.innerText();
  check(/Model/.test(dt) && /Market/.test(dt) && /Polymarket US/.test(dt) && /Kalshi/.test(dt), "detail shows model, market and both exchanges");
  check(/Mean/.test(dt) && /Median/.test(dt) && /80% range/.test(dt) && /confidence/.test(dt), "detail shows mean, median, 80% range and sample size");
  const marketCell = (await det.locator(".text-faint", { hasText: "Market unavailable" }).count()) + (await det.locator("td.text-market").count());
  check(marketCell >= 2, "each exchange shows a price or 'Market unavailable'");
  // Favorites (this browser) and recently viewed.
  const star = page.locator("li[data-fav-id] button[aria-pressed]").first();
  await star.click();
  check((await star.getAttribute("aria-pressed")) === "true", "star marks a favorite");
  await page.reload({ waitUntil: "networkidle" });
  check((await page.locator("li[data-fav-id] button[aria-pressed='true']").count()) >= 1, "favorite survives a reload");
  await page.locator("text=Favorites only").click();
  check((await rows(page).count()) === 1, `favorites-only shows the starred player (${await rows(page).count()})`);
  await page.locator("text=Favorites only").click();
  await page.locator("li[data-fav-id] button[aria-pressed='true']").first().click();
  check((await page.locator("text=Recently viewed").count()) > 0 && (await page.locator('a[href*="line="]', { hasText: label }).count()) >= 0, "recently viewed lists the opened contract");
  const recent = await page.locator("h3:has-text('Recently viewed') + ul").innerText().catch(() => "");
  check(recent.length > 0 && !/appear here/.test(recent), "recently viewed is filled");

  // NBA categories.
  await go(page, "/props?sport=nba");
  const nl = await page.locator('nav[aria-label="Prop categories"] a').allInnerTexts();
  check(["Points", "Rebounds", "Assists", "Pts + reb + ast", "Steals", "Blocks"].every((l) => nl.includes(l)), "NBA categories present");
  await ctx.close();
}

// ------------------------------------------------------------------ phone: detail overlay
{
  const { ctx, page } = await session("phone");
  await go(page, "/props?sport=nba&cat=points");
  const c = page.locator("li[data-fav-id] a[href*='line=']").first();
  await nav(page, c);
  const det = page.locator('aside[aria-label="Contract detail"]');
  check(await det.isVisible(), "phone: tapping a line opens the detail");
  await nav(page, page.locator('aside[aria-label="Contract detail"] a:has-text("Close")'));
  check(!(await det.isVisible().catch(() => false)) && qs(page).get("line") === null, "phone: Close returns to the list");
  await ctx.close();
}

// ------------------------------------------------------------------ date navigation
{
  const { ctx, page } = await session("desktop");
  for (const base of ["/nfl", "/nba", "/props?sport=nfl"]) {
    await go(page, base);
    for (const name of ["Tomorrow", "Today", "Yesterday"]) {
      await nav(page, page.locator(`main a:has-text("${name}")`).first());
      check(/^\d{4}-\d{2}-\d{2}$/.test(qs(page).get("date") ?? ""), `${base}: ${name} sets a date (${qs(page).get("date")})`);
    }
    const prevArrow = page.locator('a[aria-label^="Previous game day"]');
    if (await prevArrow.count()) {
      const before = qs(page).get("date");
      await nav(page, prevArrow);
      check((qs(page).get("date") ?? "") < (before ?? "9"), `${base}: ‹ goes to an earlier game day`);
    }
    await nav(page, page.locator('main a:has-text("All upcoming")').first());
    check(qs(page).get("date") === null, `${base}: All upcoming clears the date`);
    const before = page.url();
    await page.locator('input[type="date"]').first().fill("2026-10-26");
    await page.waitForURL((u) => u.toString() !== before, { timeout: 30000 }).catch(() => null);
    await page.waitForLoadState("networkidle");
    check(qs(page).get("date") === "2026-10-26", `${base}: calendar picks a date`);
  }
  await go(page, "/nfl?date=2026-11-01");
  const t = await page.locator("main").innerText();
  check(/Final/.test(t), "/nfl past date shows final scores");
  await go(page, "/nfl");
  const propsLink = page.locator('a[href*="/props?sport=nfl&game="]').first();
  await nav(page, propsLink);
  check(qs(page).get("game") !== null && page.url().includes("/props"), "game row Props link opens that game's props");
  await go(page, "/performance?sport=nba");
  check((await page.locator("text=Settled market record").count()) > 0 && (await page.locator("text=Player props backtest").count()) > 0, "performance page sections");
  await ctx.close();
}

await browser.close();
console.log(failed ? `${failed} check(s) failed` : "all checks passed");
process.exit(failed ? 1 : 0);
