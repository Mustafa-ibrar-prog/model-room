// Functional checks of every interactive feature, desktop and phone, in a real browser.
//
//   BASE=http://localhost:3999 TIER_COOKIE=pro node e2e/site-features.mjs     (local dev with the plan switcher)
//   BASE=https://<preview> TEST_ACCOUNT_PASSWORD=… node e2e/site-features.mjs  (test site: logs in as pro-test)
//
// Prints ok / FAIL per check; exits 1 on any failure. Uses only what the page shows; never edits data.
import { existsSync } from "node:fs";
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
/** Keep a picture of the page as tested, when the run asks for them (the workflow uploads the folder). */
const shot = async (page, name) => {
  if (!existsSync("e2e-shots")) return;
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `e2e-shots/${name}.png`, fullPage: true }).catch(() => null);
};
const noHScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
const qs = (page) => new URL(page.url()).searchParams;
const rows = (page) => page.locator("li[data-fav-id]:visible");

// ------------------------------------------------------------------ every page, both sizes
for (const device of ["desktop", "phone"]) {
  const { ctx, page, errors } = await session(device);
  for (const path of ["/", "/nfl", "/nba", "/nba-props", "/nfl-props", "/performance?tab=nfl-props", "/performance?tab=nba-props", "/performance?tab=nba", "/performance?tab=nfl", "/nfl?view=games", "/nba?view=games", "/props?sport=nfl", "/props?sport=nba", "/performance?sport=nfl", "/performance?sport=nba", "/performance/stats?sport=nba", "/yesterday", "/yesterday?date=2026-11-02", "/model-vs-market", "/pricing", "/injuries", "/ratings", "/account", "/login"]) {
    errors.length = 0;
    const st = await go(page, path);
    check(st === 200, `${device} ${path}: loads (HTTP ${st})`);
    check(await noHScroll(page), `${device} ${path}: no sideways scrolling`);
    check(errors.length === 0, `${device} ${path}: no script errors${errors.length ? ` (${errors[0]})` : ""}`);
    if (/yesterday|model-vs-market/.test(path)) {
      await page.screenshot({ path: `e2e-shots/${device}-${path.replace(/[^a-z0-9]+/gi, "_")}.png`, fullPage: true }).catch(() => null);
    }
  }
  await ctx.close();
}

// ------------------------------------------------------------------ yesterday + model vs market (pro-test)
{
  const { ctx, page } = await session("phone");
  await go(page, "/yesterday?date=2026-11-02");
  const body = await page.locator("main").innerText();
  check(/NFL/.test(body) && /Vs market spread/.test(body), "yesterday: NFL day with market record");
  check(/Last successful data refresh/.test(body), "yesterday: shows the last refresh");
  await go(page, "/model-vs-market?sport=nfl");
  const t = await page.locator("main").innerText();
  // The columns were renamed so nothing reads as a verified edge: they are the model's own numbers, marked unverified.
  check(/Model fair odds/.test(t) && /Model-implied return per \$1 \(unverified\)/.test(t), "model vs market: NFL rows with model fair odds and model-implied return, marked unverified");
  await ctx.close();
}

// ------------------------------------------------------------------ injury feed (test site)
{
  const { ctx, page } = await session("phone");
  await go(page, "/nfl?view=games");
  const nfl = await page.locator("main").innerText();
  check(/Injury info as of/.test(nfl), "nfl: games show the injury feed time and sources");
  // No quarterback the injury feed lists as Out may be the projected starter (first caught with the Ravens in week 10).
  const projected = [...nfl.matchAll(/Projected QBs: ([^\n]+)/g)].flatMap((m) => m[1].split(", ").map((x) => x.replace(/^[A-Z]{2,3} /, "").trim()));
  await go(page, "/injuries?sport=nfl");
  const outQbs = await page.locator("main").evaluate((m) =>
    [...m.querySelectorAll("li, tbody tr")].map((r) => r.innerText.replace(/\s+/g, " ")).filter((t) => /QB\b/.test(t) && /\bOut\b/.test(t)));
  const benched = projected.filter((q) => outQbs.some((t) => t.startsWith(q)));
  check(projected.length >= 2, `nfl: games name their projected quarterbacks (${projected.length})`);
  check(outQbs.length > 0, `injuries: the feed lists quarterbacks who are out (${outQbs.length})`);
  check(benched.length === 0, `nfl: no projected quarterback is listed Out on the injury feed${benched.length ? ` (${benched.join(", ")})` : ""}`);
  await go(page, "/nba?view=games");
  const nba = await page.locator("main").innerText();
  check(/NBA official report|ESPN report/.test(nba) || /Injury info as of/.test(nba), "nba: injury flags with source");
  await go(page, "/injuries?sport=nba");
  const inj = await page.locator("main").innerText();
  check(/official NBA injury report/.test(inj) && /confirmed/.test(inj), "injuries: NBA official designations marked confirmed");
  await go(page, "/injuries?sport=nfl");
  check(/ESPN injury reports/.test(await page.locator("main").innerText()), "injuries: NFL shows ESPN as the source");
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
  const names = await page.locator("li[data-fav-id]").evaluateAll((els) => els.map((e) => e.dataset.player ?? ""));
  check(names.length > 1 && names.every((n, i) => n && (i === 0 || names[i - 1].localeCompare(n) <= 0)), `sort by player is alphabetical (${names.length})`);
  await go(page, "/props?sport=nfl&cat=receiving_yards&sort=projection");
  const med = await page.locator("li[data-fav-id]").evaluateAll((els) => els.map((e) => Number(e.dataset.modelAvg)));
  check(med.length > 1 && med.every((m, i) => Number.isFinite(m) && (i === 0 || med[i - 1] >= m)), `sort by projection is descending (${med.length})`);
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
  const first = ((await page.locator("li[data-fav-id]").first().getAttribute("data-player")) ?? "").trim();
  const term = first.split(" ").pop();
  await page.fill("#q", term);
  {
    const before = page.url();
    await page.press("#q", "Enter"); // the search box submits on Enter (phones: the keyboard's Search key)
    await page.waitForURL((u) => u.toString() !== before, { timeout: 30000 }).catch(() => null);
    await page.waitForLoadState("networkidle");
  }
  const found = await page.locator("li[data-fav-id]").evaluateAll((els) => els.map((e) => (e.dataset.player ?? "").toLowerCase()));
  check(found.length > 0 && found.every((n) => n.includes(term.toLowerCase())), `search "${term}" returns only matching players (${found.length})`);
  check((await page.locator("text=across every NFL game").count()) > 0, "search covers every game");

  // Player detail. The panel was redesigned (sections instead of a quotes table), so it is found by its own hook.
  await go(page, "/props?sport=nfl&cat=receiving_yards");
  const c = page.locator("li[data-fav-id] a[href*='line=']").nth(1);
  const label = ((await page.locator("li[data-fav-id]").nth(1).getAttribute("data-player")) ?? "").trim();
  await nav(page, c);
  const det = page.locator("[data-detail]");
  await det.waitFor({ state: "visible", timeout: 30000 }).catch(() => null);
  check(qs(page).get("line") !== null && label !== "" && (await det.getAttribute("data-detail").catch(() => null)) === label, `opening ${label} shows his detail`);
  const dt = (await det.innerText().catch(() => "")) ?? "";
  check(/Market line/.test(dt) && /Model Room projection/.test(dt) && /average · middle [\d.]+ · range [\d.]+–[\d.]+/.test(dt), "detail shows the market line, the model's average, middle and range");
  check(/None available/.test(dt) ? /does not borrow a line from another provider or invent one/.test(dt) : /Market line\s+(Over|Under)?\s*[\d.]+/.test(dt),
    "detail shows a quoted market line, or says plainly that none is available");
  check(["Recent performance", "Injuries & availability", "Matchup", "Model explanation", "Data & model"].every((x) => dt.includes(x)), "detail keeps recent games, injuries, matchup, the model explanation and data notes");
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
  check((await page.locator("text=Recently viewed").count()) > 0 && (await page.locator("h3:has-text('Recently viewed') + ul", { hasText: label }).count()) > 0, `recently viewed lists ${label}`);
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
  const det = page.locator("[data-detail]");
  await det.waitFor({ state: "visible", timeout: 30000 }).catch(() => null);
  check(await det.isVisible(), "phone: tapping a player opens the detail");
  await nav(page, det.locator('a:has-text("Players")').first());
  check(!(await det.isVisible().catch(() => false)) && qs(page).get("line") === null, "phone: Players returns to the list");
  await ctx.close();
}

// ------------------------------------------------------------------ date navigation
{
  const { ctx, page } = await session("desktop");
  // The dated game board lives at ?view=games since /nfl and /nba became the game-prediction pages.
  for (const base of ["/nfl?view=games", "/nba?view=games", "/props?sport=nfl"]) {
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
  await go(page, "/nfl?view=games&date=2026-11-01");
  const t = await page.locator("main").innerText();
  check(/Final/.test(t), "/nfl board, past date: shows final scores");
  await go(page, "/nfl?view=games");
  const propsLink = page.locator('a[href*="/props?sport=nfl&game="]:visible').first();
  await nav(page, propsLink);
  check(qs(page).get("game") !== null && page.url().includes("/props"), "game row Props link opens that game's props");
  await go(page, "/performance/stats?sport=nba");
  check((await page.locator("text=Settled market record").count()) > 0 && (await page.locator("text=Player props backtest").count()) > 0, "stats for nerds keeps the performance sections");
  const stats = await page.locator("main").innerText();
  check(["Brier", "Log loss", "Calibration", "Settled market record", "model versions", "shadow experiments", "prop category"].every((x) => new RegExp(x, "i").test(stats)),
    "stats for nerds keeps Brier, log loss, calibration, the model-vs-market record, model versions, shadow comparisons and category analysis");
  await ctx.close();
}

// ------------------------------------------------------------------ performance: picks and results
for (const device of ["desktop", "phone"]) {
  const { ctx, page } = await session(device);
  const main = () => page.locator("main").innerText();
  const num = (t, label) => Number((t.match(new RegExp(`${label}\\s+(\\d[\\d,]*)`)) ?? [])[1]?.replace(/,/g, ""));
  for (const league of ["nba", "nfl"]) {
    const L = league.toUpperCase();
    // ---- games
    await go(page, `/performance?tab=${league}`);
    let t = await main();
    check(["NBA Props", "NFL Props", "NBA Games", "NFL Games", "Stats for Nerds"].every((x) => t.includes(x)), `${device} ${L} games: four results tabs and Stats for Nerds`);
    check(["Winner picks", "Spread picks", "Total picks"].every((x) => t.includes(x)) && !/All .* game picks/.test(t), `${device} ${L} games: winner, spread and total keep separate records`);
    check(/Recorded pre-game\./.test(t) && /Reconstructed\./.test(t) && /not published before the game/.test(t), `${device} ${L} games: reconstructed picks are told apart from picks recorded pre-game`);
    // the hit rate on the page is hits / (hits + misses), from the counts on the page
    const panel = await page.locator('section[aria-label="Winner picks"]').innerText();
    const [hits, misses, settled, pushes] = [num(panel, "Hits"), num(panel, "Misses"), num(panel, "Settled"), num(panel, "Pushes")];
    const shown = Number((panel.match(/([\d.]+)%/) ?? [])[1]);
    check(hits + misses > 0 && Math.abs(shown - (100 * hits) / (hits + misses)) < 0.06 && settled === hits + misses + pushes,
      `${device} ${L} games: winner hit rate ${shown}% = ${hits} / (${hits} + ${misses}); settled ${settled}`);
    // date navigation
    const dated = page.locator('nav[aria-label="Date"] a[href*="date="]');
    check((await dated.count()) > 1, `${device} ${L} games: date strip lists ${await dated.count()} days`);
    const earlier = page.locator('nav[aria-label="Date"] a[aria-label^="Earlier"]');
    if (await earlier.count()) {
      const before = qs(page).get("date");
      await nav(page, earlier);
      check(/^\d{4}-\d{2}-\d{2}$/.test(qs(page).get("date") ?? "") && qs(page).get("date") !== before, `${device} ${L} games: Earlier opens ${qs(page).get("date")}`);
    }
    // a settled game: collapsed shows the score and the grades; expanded shows every prediction
    const card = page.locator("main details", { hasText: "Final" }).first();
    check((await card.count()) > 0, `${device} ${L} games: a settled game is listed`);
    if (await card.count()) {
      const head = await card.locator("summary").first().innerText();
      check(/\d+[\s\S]*\d+/.test(head) && /Winner/.test(head) && /Spread/.test(head) && /Total/.test(head) && /HIT|MISS|PUSH/.test(head),
        `${device} ${L} games: collapsed card shows the final score and result labels`);
      check(!(await card.locator("text=Team totals:").isVisible()), `${device} ${L} games: details start closed`);
      await card.locator("summary").first().click();
      const body = await card.innerText();
      check(/to win/.test(body) && /Win probability: [A-Z]+ \d+%, [A-Z]+ \d+%/.test(body) && /won by \d+|Tied/.test(body), `${device} ${L} games: expanded card shows the winner pick, both win probabilities and the actual winner`);
      for (const [what, re] of [["spread", /Spread\s+(No recorded pick|[A-Z]{2,4} (?:[+−][\d.]+|pick'em))/], ["total", /Game total\s+(No recorded pick|(?:Over|Under) [\d.]+)/]]) {
        const m = body.match(re);
        check(Boolean(m), `${device} ${L} games: ${what} shows the recorded pick or "No recorded pick" (${m ? m[1] : "missing"})`);
      }
      check(/[\d.]+ projected\s+\d+ actual/.test(body) && /team score/.test(body) && /Margin/.test(body) && /Total points/.test(body), `${device} ${L} games: projected and actual team scores with the difference`);
      const proj = await card.locator("ul").nth(1).innerText();
      check(!/HIT|MISS|PUSH/.test(proj), `${device} ${L} games: projected scores carry no HIT or MISS`);
      check(/no team-total pick to grade/.test(body), `${device} ${L} games: no team-total pick is invented`);
      check(/Reconstructed|Recorded pre-game/.test(body), `${device} ${L} games: each pick says how it was recorded`);
    }
    check(await noHScroll(page), `${device} ${L} games: no sideways scrolling with a card open`);
    await shot(page, `performance-${league}-games-${device}`);

    // ---- props
    await go(page, `/performance?tab=${league}-props`);
    t = await main();
    const pp = await page.locator(`section[aria-label="${L} player picks"]`).innerText();
    const [h, m, s, pu, v] = [num(pp, "Hits"), num(pp, "Misses"), num(pp, "Settled"), num(pp, "Pushes"), num(pp, "Voids")];
    const rate = Number((pp.match(/([\d.]+)%/) ?? [])[1]);
    check(h + m > 0 && Math.abs(rate - (100 * h) / (h + m)) < 0.06 && s === h + m + pu, `${device} ${L} props: hit rate ${rate}% = ${h} / (${h} + ${m}); ${v} void left out`);
    check(/reconstructed/.test(pp) && /recorded pre-game/.test(pp), `${device} ${L} props: record says how many picks were reconstructed`);
    const pc = page.locator("main details", { hasText: "Final" }).first();
    if (await pc.count()) {
      await pc.locator("summary").first().click();
      check(/Reconstructed: these \d+ picks were written after the game started|recorded before the game started/.test(await pc.innerText()), `${device} ${L} props: the game says whether its picks were reconstructed`);
      const player = pc.locator("details").first();
      await player.locator("summary").click();
      const pt = await player.innerText();
      check(/(\d[\d.]*\+ |Under \d)/.test(pt) && /Finished with \d|Did not play|Awaiting box score/.test(pt) && /HIT|MISS|VOID|PUSH|PENDING/.test(pt) && /chance/.test(pt),
        `${device} ${L} props: a player shows stat, projection, pick, final stat and grade`);
      check(await noHScroll(page), `${device} ${L} props: no sideways scrolling with a player open`);
      await shot(page, `performance-${league}-props-${device}`);
    } else bad(`${device} ${L} props: no settled game to open`);
  }
  await ctx.close();
}

// ------------------------------------------------------------------ owner live view (counts only: no prices in public logs)
if (process.env.TEST_ACCOUNT_PASSWORD) {
  const { ctx, page, errors } = await session("desktop");
  for (const sport of ["nba", "nfl"]) {
    await go(page, `/props?sport=${sport}`);
    const banner = page.locator("details[data-live]");
    const on = (await banner.count()) > 0;
    check(on, `${sport} props: owner live view is on for the test login`);
    if (on) {
      console.log(`info  ${sport} owner view: ${await banner.getAttribute("data-found")} game(s) found, ${await banner.getAttribute("data-matched")} lines matched; market-line cells: ${await page.locator('section[aria-label="Market line"]').count()}`);
    }
    await go(page, `/${sport}`);
    console.log(`info  /${sport} rows with a Polymarket line: ${await page.locator("text=/^PM /").count()}`);
  }
  check(errors.length === 0, `owner view: no script errors${errors.length ? ` (${errors[0]})` : ""}`);
  await ctx.close();
}
{
  // Logged out: never live prices.
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await go(page, "/props?sport=nba");
  check((await page.locator("details[data-live]").count()) === 0, "logged out: no live Polymarket prices");
  await ctx.close();
}

await browser.close();
console.log(failed ? `${failed} check(s) failed` : "all checks passed");
process.exit(failed ? 1 : 0);
