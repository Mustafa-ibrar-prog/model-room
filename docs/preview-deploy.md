# Private preview on Vercel

A private copy of Model Room you can open on your phone, refreshed with real data every morning without your PC.

## How it works

- **`preview` branch:** `main` plus the engines' published boards (`modeling/data/published/*.json`) and its own prediction ledger (`modeling/preview-ledger/`). Nothing on it is fictional.
- **GitHub Action** (`.github/workflows/preview-refresh.yml`), daily at 13:17 UTC or on demand:
  1. Merges `main` into `preview`.
  2. Downloads data and runs validation. If validation fails, it stops and publishes nothing.
  3. Runs both engines and pushes the results to `preview`.
- **Vercel** builds only the `preview` branch: `vercel.json` turns off deployments from `main`. The preview URL is protected by Vercel's Deployment Protection, so only your Vercel login can open it.
- **No secrets:** the preview needs no API keys or database. Supabase is not used.

## One-time setup (works from an iPhone browser)

1. **Create the Vercel project.** Go to vercel.com, sign in with GitHub, then **Add New… → Project**. Import **Mustafa-ibrar-prog/model-room**. The framework is detected as Next.js; keep the defaults and tap **Deploy**. That first build is the `main` branch, which has no published projections, so it may show "Unavailable" or be skipped. That's expected.
2. **Turn on the plan switcher (preview only).** Project → **Settings → Environment Variables**:
   - Key: `ENABLE_TIER_PREVIEW`
   - Value: `true`
   - Environment: **Preview** only. Untick Production and Development.
3. **Check protection.** **Settings → Deployment Protection → Vercel Authentication** should be on, set to **Standard Protection** (the default). Preview URLs then need your Vercel login.
4. **Get the preview URL.** **Deployments**, then the latest deployment from the `preview` branch, then **Visit**. If none is listed yet, open the `preview` branch on GitHub and push any commit, or run the workflow (step 5). Bookmark the branch URL Vercel shows, `model-room-git-preview-<your-team>.vercel.app`; it always points at the newest preview build.
5. **Refresh on demand.** In the GitHub app: **model-room → Actions → Refresh preview data → Run workflow**.

## Keeping production safe

- `main` is never pushed to by the workflow; it only reads from it.
- Vercel won't deploy `main` while `vercel.json` disables it, so no production URL gets built from this project.
- The production domain stays unassigned until you decide to launch.

## Player props in the preview

The daily refresh also runs `nfl props`. It does **not** fetch Polymarket US or Kalshi prices. The repository is public, the published board is committed to it, and both exchanges' terms forbid republishing their data. Exchange comparison runs on your own machine (`docs/markets.md`).

The `preview` branch is public on GitHub, so anyone can read the projections in `modeling/data/published/`. Make the repository private before those numbers are something you charge for.

## Limits

- Data refreshes once a day. The status bar under the header shows each league as Current, Delayed or Unavailable. Projections older than 30 hours always show as Delayed.
- The preview's ledger is separate from `main`'s, so test predictions made in the preview don't mix with your local history.
- Vercel's Hobby plan is free for personal, non-commercial use. Move to Pro before charging customers.
