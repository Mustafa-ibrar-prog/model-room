# Owner analytics dashboard (TEST only)

`/owner` on the test site. Private to the owner, read-only, never available in production.

## Who can open it

Checked twice on the server for every request: first in the request proxy (`src/proxy.ts`), before anything renders,
then by `requireOwner()` in the page and in every data loader (`src/server/owner/`).

| Condition | Result |
| --- | --- |
| Production deployment (`VERCEL_ENV=production` or `MODELROOM_ENV=production`) | 404 for everyone |
| `OWNER_EMAILS` unset, empty, malformed, or holding more than one address | 404 for everyone |
| `OWNER_EMAILS` is a test account (`@modelroom.test`) | 404 for everyone |
| Signed in as the one address in `OWNER_EMAILS` | Dashboard |
| Anyone else, any tier, including the tier-preview cookie | 404 (the site's ordinary not-found page) |

There is no API route, no client component and no public JSON for the dashboard; responses are `private, no-store`.

## Database access (read-only role)

Migration `supabase/migrations/20261112000100_owner_reader.sql` creates `owner_reader`. It can `SELECT` exactly
`odds.snapshots`, `odds.comparisons`, `odds.reports` and `scheduler.health`. It cannot insert, update, delete,
truncate or create anything, its sessions are read-only by default (15 s statement timeout, 5 connections), and it
**cannot log in until you give it a password**. The app also wraps every query in a `READ ONLY` transaction.

Without the connection string, the sections that need the database show "unavailable"; nothing is estimated.

### One-time setup (you do this; never paste the password or URL into chat)

1. **Set the password.** Supabase → the TEST project → SQL Editor → run, with a new long random password
   (letters and digits only, 32+ characters, from your password manager):

   ```sql
   alter role owner_reader with login password 'PASTE-A-NEW-RANDOM-PASSWORD';
   ```

2. **Build the connection string.** Supabase → Connect → **Transaction pooler** (port 6543). Copy it and change two
   things: the user `postgres.<project-ref>` becomes `owner_reader.<project-ref>`, and the password becomes the one
   from step 1. Add `?sslmode=require` if it is not there. Shape:

   ```
   postgresql://owner_reader.<project-ref>:<password>@<region>.pooler.supabase.com:6543/postgres?sslmode=require
   ```

3. **Add it to Vercel (TEST only).** Vercel → model-room → Settings → Environment Variables → Add:
   - Key: `MODELROOM_OWNER_DB_URL`
   - Value: the string from step 2
   - Environments: **Preview only** (untick Production and Development)
   - Sensitive: on
   Then Deployments → the latest Preview deployment → ⋯ → Redeploy (or wait for the next refresh deploy).

4. **Check `OWNER_EMAILS`.** Same page: the Preview value must be exactly one address, yours. Two or more addresses,
   or a test account, turn the dashboard off for everyone (by design).

5. **Verify.** Signed in as yourself, open `/owner` on the test site: the header says "Read-only database:
   configured" and section 1 shows data. Signed out, or as a test account: the ordinary 404 page.

To revoke access at any time: `alter role owner_reader nologin;` (or delete the Vercel variable).

### Read-only verification you can run in the SQL editor

```sql
select n.nspname || '.' || c.relname as object,
       has_table_privilege('owner_reader', c.oid, 'SELECT') as can_read,
       has_table_privilege('owner_reader', c.oid, 'INSERT') or has_table_privilege('owner_reader', c.oid, 'UPDATE')
         or has_table_privilege('owner_reader', c.oid, 'DELETE') or has_table_privilege('owner_reader', c.oid, 'TRUNCATE') as can_write
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind in ('r', 'v', 'm', 'p', 'f') and n.nspname not in ('pg_catalog', 'information_schema')
  and (has_table_privilege('owner_reader', c.oid, 'SELECT') or has_table_privilege('owner_reader', c.oid, 'INSERT'))
order by 1;
```

Expected: four rows (`odds.comparisons`, `odds.reports`, `odds.snapshots`, `scheduler.health`), every `can_write`
false. The full test, including a login as the role, is `supabase/tests/owner_reader_test.sql` (scratch databases only:
it inserts a test row).

## Sections

1. Line movement · 2. Model vs market · 3. Prop performance · 4. Calibration · 5. Active vs shadow ·
6. Version history · 7. Freshness & scheduler · 8. Sportsbook detail.

Rules: observed market data (white) and model estimates (blue, with version) are styled apart; sample gates come from
the existing validation (props) and the 250-settled-game gate (sportsbook markets); no ROI, profit, EV or edge
figures; comparisons persisted from 2026-11-12 onward are labelled unvalidated, not settled evidence.

## Local development

`next dev` only (never on Vercel): `MODELROOM_DEV_SESSION_EMAIL` stands in for the signed-in email, so with
`OWNER_EMAILS` set to the same address the dashboard opens without the TEST Supabase project.
