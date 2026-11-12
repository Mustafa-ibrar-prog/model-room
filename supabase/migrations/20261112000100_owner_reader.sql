-- Read-only database role for the owner analytics dashboard (TEST SITE ONLY).
--
-- owner_reader can SELECT exactly four objects and nothing else:
--   odds.snapshots     sportsbook lines as collected (append-only)
--   odds.comparisons   model-vs-book comparisons at matching timestamps (append-only)
--   odds.reports       private analysis reports per run (append-only)
--   scheduler.health   refresh scheduler status view (counts and timestamps; never the token)
-- No INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES or TRIGGER; no CREATE on any schema; no function execution
-- beyond Postgres defaults; no access to public, auth, storage, private or any other schema's tables.
-- Every session is read-only by default and time-limited.
--
-- The role is created WITHOUT a password and cannot log in until the owner runs, in the Supabase SQL editor
-- of the TEST project:
--     alter role owner_reader with login password '<a long random password>';
-- The password is never stored in this repository or in chat. See docs/owner-dashboard.md.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'owner_reader') then
    create role owner_reader nologin noinherit nocreatedb nocreaterole noreplication;
  end if;
end $$;

-- Read-only by default; short limits so a slow query can never hold resources.
alter role owner_reader set default_transaction_read_only = on;
alter role owner_reader set statement_timeout = '15s';
alter role owner_reader set idle_in_transaction_session_timeout = '30s';
alter role owner_reader connection limit 5;

-- Nothing but USAGE on the two schemas it reads.
revoke all on schema odds, scheduler from owner_reader;
grant usage on schema odds, scheduler to owner_reader;
revoke create on schema public from owner_reader;

-- SELECT on exactly the four objects, nothing more.
revoke all on table odds.snapshots, odds.comparisons, odds.reports from owner_reader;
grant select on table odds.snapshots, odds.comparisons, odds.reports to owner_reader;
revoke all on table scheduler.health from owner_reader;
grant select on table scheduler.health to owner_reader;

-- Row level security stays on for the odds tables; owner_reader gets a SELECT-only policy (API roles still none).
drop policy if exists owner_reader_select on odds.snapshots;
create policy owner_reader_select on odds.snapshots for select to owner_reader using (true);
drop policy if exists owner_reader_select on odds.comparisons;
create policy owner_reader_select on odds.comparisons for select to owner_reader using (true);
drop policy if exists owner_reader_select on odds.reports;
create policy owner_reader_select on odds.reports for select to owner_reader using (true);

comment on role owner_reader is 'Model Room TEST: read-only access for the owner dashboard (odds.* and scheduler.health, SELECT only).';
