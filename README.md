# Model Room

NFL and NBA sports analytics: market lines next to model projections for spreads, totals, player props, injury impact and team ratings.

> **Status:** Phase 1 (interface) and Phase 2 (database and membership foundation) are done. Every team, player and number in the app is still **fictional demonstration data**. No projection engine is implemented, and nothing on the site is a prediction. Shopify login is designed ([docs/auth-architecture.md](docs/auth-architecture.md)) but not built.

## Stack

- [Next.js 16](https://nextjs.org) (App Router, Cache Components) with TypeScript
- Tailwind CSS v4
- Supabase Postgres for profiles, memberships and sports data, with Row Level Security on every table
- Vercel for hosting
- Shopify customer accounts and subscriptions (designed, not yet connected)

## Run it

```bash
npm install
cp .env.example .env.local   # optional; the app runs with no env vars
npm run dev                  # http://localhost:3000
```

Other scripts:

```bash
npm run build   # production build
npm start       # serve the production build
npm run lint
npm run check:entitlements   # app plan rules match the database
npm run db:test              # migrations + 94 security tests on a local Postgres
```

### Previewing paid plans

Set `ENABLE_TIER_PREVIEW=true` in `.env.local`. A switcher appears at the bottom of every page to view the site as Free, Plus or Pro. It sets an httpOnly cookie through a server action, and it does nothing when the variable is unset, so keep it off in production.

### Plan preview needs the flag at build time

Pages prerender as Free unless `ENABLE_TIER_PREVIEW=true` is set when you run `next build` (or `next dev`). Once Shopify login ships, pages that read the session render per request automatically.

## Database

Schema, relationships and security rules: [docs/database.md](docs/database.md). Migrations are in `supabase/migrations/`.

```bash
npx supabase link --project-ref <project-ref>
npx supabase db push
```

- Sign-ups through Supabase are turned off. Accounts will be created by the server after a Shopify login.
- The app reads a signed-in user's tier from `public.effective_tier_for()` (`src/server/membership.ts`). Any error resolves to Free.
- `SUPABASE_SERVICE_ROLE_KEY` is used only in `src/lib/supabase/admin.ts`, which imports `server-only`.

## Project structure

```
src/
  app/                    Routes (pages + API)
    page.tsx              Home: hero, board preview, insights, injuries, How it works, Data sources
    nfl/ nba/             League game boards
    props/ injuries/ ratings/
    pricing/              Plans and feature comparison
    api/v1/games/         GET ?league=nfl|nba — gated JSON
  components/
    layout/               Header, footer, demo banner, logo
    tables/               Server components that fetch gated data and render boards
    marketing/            Hero, How it works, Data sources, pricing cards
    ui/                   Panels, lock cells, table cells, skeletons
    dev/                  Plan preview switcher (dev only)
  config/tiers.ts         Plan names, prices, feature copy
  lib/
    entitlements.ts       Which plan unlocks which feature (single source of truth)
    format.ts             Number formatting
    supabase/server.ts    Supabase server client with the public key (returns null until configured)
    supabase/admin.ts     Service-role client, server only
  server/                 Server-only code (imports "server-only")
    viewer.ts             Who is viewing and which plan they hold
    session.ts            Signed-in user id (returns null until Shopify login ships)
    membership.ts         Tier lookup from Supabase
    data/                 Data Access Layer: gates every field before it leaves the server
    providers/            Data providers; demo/ holds the fictional dataset
    actions/              Server actions
  engines/                Modeling engine contracts (no UI imports, no algorithms yet)
  types/domain.ts         Shared domain types
supabase/
  migrations/             Database schema, RLS, functions
  tests/                  Security test suite + Supabase shim for plain Postgres
docs/
  database.md             Tables, relationships, rules
  auth-architecture.md    Shopify customer login and subscription sync design
scripts/                  db-test.sh, check-entitlements-sync.mjs
```

## How membership gating works

1. `getViewer()` (`src/server/viewer.ts`) resolves the viewer's plan. In Phase 1 everyone is Free unless the dev preview is on.
2. Pages and the API call the Data Access Layer (`src/server/data`) with that plan.
3. The DAL passes each premium field through `gate()` from `src/lib/entitlements.ts`. Fields the plan doesn't include are replaced with `{ locked: true, requires: "plus" }`. The real value is never serialized.
4. The UI only renders what it receives. Locked fields show a lock and a link to pricing.

This applies the same way to HTML, React Server Component payloads and `/api/v1/*` JSON, so premium data can't be scraped from the frontend. Free viewers get no player prop data at all.

To change who gets what, edit `MIN_TIER` in `src/lib/entitlements.ts` and the copy in `src/config/tiers.ts`.

Because `getViewer()` will read cookies, components that call it must render inside `<Suspense>`. That's a Cache Components rule, and every board already follows it.

## Data and engines

- **Providers** (`src/server/providers`) supply raw records. `getProvider()` picks one from `MODEL_ROOM_DATA_SOURCE`. Only `demo` exists.
- **Engines** (`src/engines`) will compute projections. They take typed inputs and return typed outputs, with no access to plans, React or Next.js. They currently throw `EngineNotImplementedError`. See `src/engines/README.md`.
- Engines should run as scheduled jobs that write to Supabase. A future `live` provider reads those stored projections. Pages never call engines directly.

The demo banner and "Demo data" stamps should come off only once a live, validated provider is active.

## Design tokens

Defined in `src/app/globals.css`. Each color has a fixed meaning across the app:

| Token | Hex | Meaning |
| --- | --- | --- |
| `navy-950` | `#061020` | Page background |
| `navy-900` | `#0a182c` | Panels |
| `market` (blue) | `#4c8dff` | Posted market lines |
| `model` (teal) | `#2fd3b5` | Model Room numbers, primary actions |
| `edge` (orange) | `#ff8a3d` | The gap between market and model, notices |

Type: Barlow Condensed for headings and numbers, Barlow for body text. Both are self-hosted through `@fontsource`.

## Deploying to Vercel

Import the GitHub repo in Vercel. No environment variables are required for Phase 1. Leave `ENABLE_TIER_PREVIEW` unset on production. You can set it on preview deployments if you want the switcher there.

## Roadmap

- **Phase 2 (done):** Supabase schema, RLS, membership tiers linked to the app's entitlements.
- **Phase 2b:** Shopify customer login and subscription sync, once the design in `docs/auth-architecture.md` is approved.
- **Phase 3:** Data ingestion jobs for schedules, lines and injury reports.
- **Phase 4:** NFL and NBA engines, backtested before going live.
- **Phase 5:** Shopify subscriptions mapped to plans, watchlists, alerts, history and downloadable reports.
