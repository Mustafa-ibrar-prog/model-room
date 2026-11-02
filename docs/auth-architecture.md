# Authentication architecture

> **Update 2026-11-02: superseded.** At the owner's request, logins use **Supabase email + password** (free tier), not Shopify customer accounts. The membership tables, security rules and `effective_tier_for()` described below are unchanged and are what the site uses.
>
> - Code: `src/server/session.ts`, `src/server/actions/auth.ts`, `src/app/{login,signup,forgot-password,reset-password,account,upgrade}`, `src/proxy.ts`.
> - Test accounts: `scripts/seed-test-accounts.mjs`, `.github/workflows/supabase-preview.yml`.
> - Payments aren't connected yet. Paid tiers are granted manually (admin memberships) until a Shopify subscription app is set up. The Shopify sections below remain the plan for billing, not for login.

Original proposal (kept for reference):

## Goals

- Customers sign in with their Shopify customer account. No second password.
- One identity across Shopify and Model Room.
- Plus and Pro come from Shopify subscriptions.
- Supabase stores profiles, memberships and permissions.
- Nothing built now has to be thrown away later.

## Recommendation

**Shopify is the identity provider. The Model Room server is an OAuth client of Shopify's Customer Account API. Supabase is the profile and permission store.**

```
 Browser            Model Room (Next.js on Vercel)             Shopify                     Supabase
 -------            ------------------------------             -------                     --------
 Sign in  ───────▶  /auth/login
                    state + nonce + PKCE ─────────────────────▶ Customer account login
                                                                (email code, Shop, passkey)
          ◀───────────────────────────────────────────────────  redirect with code
          ───────▶  /auth/callback
                    exchange code (client secret + PKCE) ─────▶ token endpoint
                    verify id_token (JWKS, nonce, expiry)
                    Customer Account API: customer.id ────────▶ gid://shopify/Customer/…
                    find or create user by customer GID ───────────────────────────────────▶ auth.users, profiles,
                                                                                              customer_identities
                    read subscription contracts ───────────────▶ (login-time check)
                    upsert membership ─────────────────────────────────────────────────────▶ memberships
                    set encrypted httpOnly session cookie
 Pages    ───────▶  getViewer(): cookie → user id → effective_tier_for() ─────────────────▶ tier
```

### Login

1. `/auth/login` creates `state`, `nonce` and a PKCE verifier, stores them in a short-lived httpOnly cookie, and redirects to the store's authorization endpoint. The endpoint comes from discovery at `https://<store-domain>/.well-known/openid-configuration`, never hardcoded. Scopes are `openid email customer-account-api:full`.
2. The customer signs in on Shopify's hosted page. It's the same login they use on the storefront, so the identity is shared.
3. `/auth/callback` checks `state` and exchanges the code as a **confidential client** (the client secret stays on the server). It then verifies the id_token signature against Shopify's JWKS and checks the nonce and expiry.
4. The server asks the Customer Account API for `customer { id }`. That GID (`gid://shopify/Customer/<n>`) is the permanent key. It's the same ID the Admin API, webhooks and Flow use.
5. It looks up `customer_identities` by shop and GID:
   - **Found:** use that profile.
   - **Not found:** create a Supabase auth user with the admin API (no password, email copied from Shopify). The database trigger creates the profile, and the server inserts the identity link.
   - Accounts are never linked by email alone.
6. The server sets Model Room's own session: an encrypted, httpOnly, SameSite=Lax cookie holding the profile id and expiry. `getSessionUserId()` in `src/server/session.ts` reads it, and nothing else needs to change.
7. Logout clears the cookie and redirects to Shopify's `end_session_endpoint` with `id_token_hint`.

### Why the server holds the session (and not Supabase Auth in the browser)

- Premium data is already read only on the server, through the data access layer. The browser never needs a database connection.
- Row Level Security still guards every table, so a leaked public key reads nothing premium. The policies already use `auth.uid()`. If browsers ever get Supabase sessions, the rules are in place.
- Supabase sign-ups are turned off (`supabase/config.toml`), so no second login system can appear.

### Alternatives considered

| Option | Verdict |
| --- | --- |
| Supabase email, password or magic-link login | Rejected. It's a second, disconnected identity, which is what you asked to avoid. |
| Supabase custom OIDC provider pointed at Shopify | Cleanest on paper: Supabase would run the whole login. However, developers report that Shopify's id_token has an issuer that doesn't match discovery and no `aud` claim, which strict validators reject. Supabase has no hook to adjust the token. Worth a 30-minute test on a dev store. If it works, it can replace steps 3–6 without any schema change, because profiles are keyed to `auth.users` either way. |
| Multipass | Rejected. It's legacy, Plus-only, unavailable to new stores, and doesn't work with the Customer Account API. |
| Model Room as the identity provider for Shopify | Rejected. "Bring your own identity provider" requires Shopify Plus, and Shopify should own the customer login. |

## Subscriptions to memberships

Model Room never runs checkout. Customers buy Plus or Pro on Shopify as subscription products (selling plans) through a subscription app such as Shopify Subscriptions.

A separate app can't read subscription contracts created by another app through the Admin API; `read_own_subscription_contracts` only covers contracts the app created. So membership changes reach Model Room three ways:

1. **Shopify Flow (primary, near real time).** A Flow on the subscription contract triggers ("created" and the status-change trigger) runs "Send HTTP request" to `POST /api/webhooks/shopify/flow`. The request carries the customer GID, contract GID, status, selling plan and next billing date, and is signed with a shared secret header.
   - The server verifies the secret, records the delivery in `shopify_webhook_events` (so it's processed once), maps the selling plan to a tier, and upserts `memberships` with the service role.
2. **Login-time check (backstop).** At each login the server reads the customer's subscription contracts through the Customer Account API with the customer's own token, then reconciles `memberships`.
3. **Optional nightly reconciliation.** The same Flow also writes a customer metafield (for example `model_room.membership`). A small custom app with `read_customers` compares it against the database.

Status mapping:

| Shopify contract | `memberships.status` | Access |
| --- | --- | --- |
| ACTIVE | active | yes |
| FAILED billing (retrying) | past_due | yes, during the grace window |
| PAUSED | paused | no |
| CANCELLED | cancelled | until `current_period_end` (+3 days) |
| EXPIRED | expired | no |

Shopify memberships can only change through these sync paths. `admin_end_membership()` refuses them, so the database and Shopify can't disagree.

## What you need to set up in Shopify

1. **Choose the store.** Options are the existing Computer Citi store or a separate Model Room store. Customer identity is shared only within one store. Before deciding, check Shopify's and Shopify Payments' acceptable-use terms for sports-betting analytics subscriptions.
2. Turn on **new customer accounts** (Settings → Customer accounts).
3. Install the **Headless** sales channel and create a storefront. Under **Customer Account API**:
   - Set the client type to **Confidential**.
   - Add the callback URI `https://<model-room-domain>/auth/callback`.
   - Add the logout URI `https://<model-room-domain>/`.
   - Copy the client ID, client secret and the numeric shop ID.
4. Use HTTPS on a real domain. Shopify does not allow `localhost` callbacks. Use the Vercel domain, or a tunnel such as ngrok for local work.
5. Install a subscription app and create **Plus ($14.99/mo)** and **Pro ($29.99/mo)** selling plans. Record each selling plan GID for the tier map.
6. In Shopify Flow, create the "Send HTTP request" workflows described above. Confirm that your plan includes Flow's HTTP request action and the subscription contract triggers.

## Environment variables (when login is built)

| Variable | Where | Purpose |
| --- | --- | --- |
| `SHOPIFY_STORE_DOMAIN` | server | Store domain for OIDC discovery |
| `SHOPIFY_SHOP_ID` | server | Numeric shop id stored on identity links |
| `SHOPIFY_CUSTOMER_ACCOUNT_CLIENT_ID` | server | Customer Account API client |
| `SHOPIFY_CUSTOMER_ACCOUNT_CLIENT_SECRET` | server, secret | Confidential client secret |
| `SHOPIFY_FLOW_WEBHOOK_SECRET` | server, secret | Verifies Flow requests |
| `SHOPIFY_PLAN_MAP` | server | JSON: selling plan GID → `plus` / `pro` |
| `MODEL_ROOM_SESSION_SECRET` | server, secret | 32+ byte key for the session cookie |
| `APP_URL` | server | Public HTTPS origin used to build callback URLs |

None of these use the `NEXT_PUBLIC_` prefix, so none can reach the browser.

## Sources

- [Shopify: Authenticate customers with the Customer Account API](https://shopify.dev/docs/storefronts/headless/building-with-the-customer-account-api/authenticate-customers)
- [Shopify: Customer Account API with Hydrogen/Headless (channel setup, HTTPS requirement)](https://shopify.dev/docs/storefronts/headless/building-with-the-customer-account-api/hydrogen)
- [Shopify: Customer authentication (bring your own IdP, Plus only)](https://shopify.dev/docs/api/customer-authentication)
- [Shopify community: detecting subscriptions created by Shopify Subscriptions (Flow recommendation)](https://community.shopify.dev/t/recommended-pattern-for-non-subscription-apps-to-detect-active-subscriptions-created-by-shopify-subscriptions/32590)
- [Shopify: About subscription contracts](https://shopify.dev/docs/apps/build/purchase-options/subscriptions/contracts)
- [Shopify Flow: Subscription contract created trigger](https://help.shopify.com/en/manual/shopify-flow/reference/triggers/subscription-contract-created)
- [Supabase: Custom OAuth/OIDC providers](https://supabase.com/docs/guides/auth/custom-oauth-providers)
- [NextAuth discussion: Shopify Customer Account API id_token quirks](https://github.com/nextauthjs/next-auth/discussions/9392)
