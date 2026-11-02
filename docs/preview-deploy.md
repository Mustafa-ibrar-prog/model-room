# Test site (Vercel preview)

The test site is the `preview` branch on Vercel, at a fixed address:

**https://model-room-git-preview-computer-citi.vercel.app**

Anyone with the link can open it once Vercel Authentication is turned off for previews (see setup). It is labeled "Test site", and search engines are told not to index it.

## Where to work

| Branch | What it is | Who writes to it |
|---|---|---|
| `main` | **Development.** All code and model changes go here. | You and Claude |
| `preview` | `main` + generated projections. This is what Vercel builds for the test site. | Only the GitHub Action (never edit by hand) |
| production | **Not set up yet.** When you launch, create a `production` branch and point Vercel's production deployments at it. Nothing reaches it unless you merge on purpose. | You, deliberately |

Work on `main`. Every push to `main` updates the test site automatically.

## What happens on a push

The workflow is `.github/workflows/preview.yml`.

1. **Within about a minute:** `main` is merged into `preview`, and Vercel rebuilds the test site, which takes 1–2 minutes.
2. **If the push changed `modeling/`** (an engine or its settings), the workflow first downloads data, validates it, and re-runs every engine: NBA and NFL games, plus NFL and NBA props. It then rebuilds the results history and the graded performance record from the ledger (`python -m modelroom history`). That takes about 10 minutes.
3. **Twice a day** (5:17 AM and 1:47 PM Pacific) it refreshes the data the same way, so the test site always has the latest projections.
4. **If validation or a model run fails,** the site keeps the last good projections (shown as Delayed after 30 hours), and the run shows a red ✗ in GitHub → Actions.

To refresh by hand: in the GitHub app, open **model-room → Actions → Preview → Run workflow**.

## One-time setup: make the test site public

1. Open vercel.com/computer-citi/model-room/settings/deployment-protection
2. Under **Vercel Authentication**, switch it **off**, or choose the option that leaves preview deployments unprotected.
3. Tap **Save**.
4. Check it: open the test-site link in a Private tab. It should load without a Vercel login.

## Logins and test accounts

Logins are Supabase email + password. They switch on once these are set:

| Where | Name | Value |
|---|---|---|
| Vercel → Environment Variables (**Preview** only) | `NEXT_PUBLIC_SUPABASE_URL` | Project URL |
| | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon / publishable key |
| | `SUPABASE_SERVICE_ROLE_KEY` | service_role / secret key (server only) |
| GitHub → Settings → Secrets → Actions | `SUPABASE_DB_URL` | database connection string with your password |
| | `SUPABASE_URL` | Project URL |
| | `SUPABASE_SERVICE_ROLE_KEY` | service_role key |
| | `TEST_ACCOUNT_PASSWORD` | the test accounts' password |

Then:

1. **Set up the database.** In the GitHub app, go to Actions → **Supabase (test site)** → **Run workflow**. This applies the migrations and creates the three test accounts:

   | Email | Plan |
   |---|---|
   | free-test@modelroom.test | Free |
   | plus-test@modelroom.test | Plus |
   | pro-test@modelroom.test | Pro |

2. **Tell Supabase where the site lives.** In Supabase, go to Authentication → URL Configuration:
   - Set **Site URL** to the test-site address.
   - Add `https://model-room-git-preview-computer-citi.vercel.app/**` under **Redirect URLs**.

3. **Redeploy** the preview (push anything, or run the Preview workflow) so it picks up the new Vercel settings.

How it works once on:

- **Test accounts work on the test site only.** Sign-in refuses `@modelroom.test` addresses in production, and the setup script refuses to run for anything but the test site.
- **The account page shows simulation buttons for test accounts.** They can upgrade, downgrade, cancel (access continues 7 days) or expire, all without payment. The site then checks access on the server exactly as for a real customer.
- **The Free / Plus / Pro switcher disappears** once logins are on, so plans only come from accounts.
- **Supabase's built-in email** (confirmations, password resets) is free but limited to a few emails an hour. That's fine for testing. Before launch, connect an email provider; free tiers exist, and I'll ask before adding anything paid.

## Environment and secrets

- **Secrets live only in Vercel and GitHub settings:** the Supabase keys above, and nothing else. No exchange prices are fetched for the test site: the repository is public, and the Polymarket US and Kalshi terms don't allow republishing their data.
- **`.env.production` exists on the `preview` branch only.** It turns on the Free / Plus / Pro switcher. It isn't a secret and never exists on `main`.
- **Never put API keys in the repository.** Locally they go in `.env.local`, which is gitignored.

## Good to know

- The repository is public, so the projections on the `preview` branch can also be read on GitHub. Make the repository private before those numbers are something you charge for.
- Anyone on the test site can use the plan switcher to see Pro features. That's intended for testing, and it goes away when logins replace it.
- Vercel's Hobby plan is free for personal, non-commercial use. Move to Pro before charging customers.
