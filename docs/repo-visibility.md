# Repository visibility: checks, switch and recovery

Model Room's repository was public while the test site was being built. Public meant three things worth
ending: every generated file was world-readable (sportsbook names and lines were published in game-board
JSON until 2026-11-12, and older versions of those files are still in the branch history), the Odds API's
terms are easier to honour when nothing is downloadable by strangers, and the research branches held raw
scraped pages. Private also costs something: GitHub Actions minutes stop being free.

This file records what was checked before the switch, how to make it, and how to undo it.

## What changes and what does not

| | Public | Private |
|---|---|---|
| Generated JSON, ledgers, history | anyone with the URL | only people with repo access |
| GitHub Actions minutes | free, unmetered | billed against the account's included minutes |
| Actions secrets, variables, `GITHUB_TOKEN` | unchanged by visibility | unchanged by visibility |
| Supabase `pg_net` dispatch (PAT) | works | works if the PAT grants this repo Actions: write |
| Vercel Git deployments | works | works for a **personal** repo on any plan |
| Forks, stars, clones by strangers | possible | not possible |
| Existing deployment URLs | unchanged | unchanged |

### Actions minutes are the real cost

GitHub Free includes about 2,000 Linux minutes a month on private repositories; Pro about 3,000. A
two-core Linux runner is billed at $0.008/minute above that, and every job is rounded up to the whole
minute. Before the wake-time scheduler (2026-11-13) the Preview workflow was started every ten minutes
and would have billed roughly 14,700 minutes a month. After it, about 11 real refreshes a day plus a few
no-op checks come to roughly 1,300–2,000 minutes a month. Going private before that change would have
cost over $100 a month; this is why the scheduler change came first.

## Checked before the switch (2026-11-13)

- **Owner and kind.** `Mustafa-ibrar-prog` is a personal account, not an organization, and the repository
  is not a fork. 0 forks, 1 star, GitHub Pages not enabled, no rulesets, no protected branches.
- **Vercel.** Vercel's documented restriction is organization-only: "You cannot deploy to a Hobby team
  from a private repository in a GitHub organization, GitLab group, or Bitbucket workspace," and the
  commit-author check "does not apply to collaborators on personal Git accounts". This repository is
  personal, so Git deployments keep working, including the `preview` commits authored by
  `github-actions[bot]`. Verified empirically after the switch by watching the next `preview` deployment.
- **Nothing depends on public read.** No code, workflow or script fetches this repository over
  `raw.githubusercontent.com` or an unauthenticated API. The only `raw.githubusercontent.com` reads are
  other people's public datasets (nflverse, sportsdataverse), which are unaffected. `vercel.json` disables
  deployments for `main`; production is not deployed from this repository at all.
- **Actions.** Secrets, variables and workflow permissions are properties of the repository and do not
  change with visibility. Every workflow already reads its secrets by name, so none of them needs editing.
- **Supabase.** `scheduler.dispatch_refresh()` calls the GitHub REST API with a token from Vault. A
  fine-grained token (`github_pat_…`) names this repository explicitly and keeps working. A classic token
  works only if it has the whole `repo` scope: `public_repo` alone stops working the moment the repository
  is private. The token's shape is printed (never its value) by the "Scheduler diagnostics" workflow.
- **Access.** Collaborators can only be listed from the repository's Settings → Collaborators page; the
  API path is blocked from this environment. Anyone who should keep access must be a collaborator before
  the switch, because a private repository is invisible to everyone else.

## Making the switch

Settings → General → Danger Zone → Change repository visibility → Make private. Then, in order:

1. Run **Scheduler diagnostics** (Actions → Scheduler diagnostics (test site) → Run workflow). The
   dispatch log must show `status_code` 204 and no 404s. A 404 means the Vault token can no longer see the
   repository: replace it with a fine-grained token granting Actions: write on this repository.
2. Wait for the next scheduled refresh (or Actions → Preview → Run workflow with mode `force`) and confirm
   the run finishes and the `preview` branch gets its commit.
3. Confirm Vercel built that commit: Vercel → the project → Deployments, newest entry on branch `preview`,
   status Ready.
4. Open the test site and confirm the boards show the new `generated_at`.

## Recovery

Making a repository private is reversible and loses nothing: commits, branches, tags, Actions history,
secrets, settings and deployments all survive in both directions.

- **Vercel stops deploying.** Settings → General → Change repository visibility → Make public, and the next
  push deploys as before. The site itself keeps serving the last good deployment while this is sorted out,
  so nothing goes down in the meantime.
- **Supabase dispatch starts failing (404 or 403 in `scheduler.dispatch_log`).** Either put a fine-grained
  token with Actions: write into Vault (`select vault.create_secret(...)`, see `docs/database.md`), or make
  the repository public again. The GitHub cron in `preview.yml` (`7 */6 * * *`) keeps refreshing the site
  every six hours in the meantime, so the data does not go stale while the token is replaced.
- **Actions minutes run out.** Billing → Plans and usage shows the remaining included minutes. The cheapest
  lever is the refresh schedule in `modeling/modelroom/refresh_plan.py`: dropping the afternoon slot or the
  per-game pre-game slots reduces runs directly. Making the repository public again removes the metering
  entirely.
- **Someone loses access.** Add them as a collaborator (Settings → Collaborators), or make the repository
  public again.

Nothing in the switch touches production, the models, the prediction ledgers or the Odds API.
