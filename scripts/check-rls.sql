-- Row-level security and privilege checks for the TEST SITE's database. Read-only: everything runs in a
-- transaction that is rolled back. Run by .github/workflows/supabase-preview.yml after the test accounts
-- exist:  psql "$DB_URL" -v ON_ERROR_STOP=1 -qtA -f scripts/check-rls.sql
--
-- Expected design (supabase/migrations/20261102000700_row_level_security.sql):
--   * RLS is on for every public table.
--   * anon has no privileges at all on private account tables, so a query is refused outright
--     ("permission denied"), which is stronger than RLS returning zero rows.
--   * authenticated may SELECT memberships, and the "Read own memberships" policy limits rows to
--     user_id = auth.uid(). No one but the server (service role) can write them.
begin;

do $$
declare
  free_id uuid; plus_id uuid; n int; own int; others int;
  private_tables text[] := array['memberships', 'membership_events', 'profiles', 'user_roles', 'customer_identities'];
  t text; p text;
begin
  -- 1. RLS is on everywhere in public.
  select count(*) into n from pg_tables where schemaname = 'public' and not rowsecurity;
  if n > 0 then raise exception 'FAIL  % public table(s) have row-level security off', n; end if;
  raise notice 'ok    row-level security is on for every public table';

  -- 2. Privileges, checked from the catalog (no role switching needed).
  foreach t in array private_tables loop
    foreach p in array array['SELECT', 'INSERT', 'UPDATE', 'DELETE'] loop
      if has_table_privilege('anon', format('public.%I', t), p) then
        raise exception 'FAIL  anon has % on public.%', p, t;
      end if;
    end loop;
  end loop;
  raise notice 'ok    anonymous visitors have no privileges on account tables (%)', array_to_string(private_tables, ', ');
  if not has_table_privilege('authenticated', 'public.memberships', 'SELECT') then
    raise exception 'FAIL  signed-in users cannot read memberships at all (the site needs SELECT, limited by RLS)';
  end if;
  foreach p in array array['INSERT', 'UPDATE', 'DELETE'] loop
    if has_table_privilege('authenticated', 'public.memberships', p) then
      raise exception 'FAIL  signed-in users have % on memberships (plans must be server-written only)', p;
    end if;
  end loop;
  raise notice 'ok    signed-in users may read memberships but not write them';
  if has_function_privilege('anon', 'public.test_simulate_membership(text)', 'EXECUTE') then
    raise exception 'FAIL  anonymous visitors can call test_simulate_membership';
  end if;
  if has_table_privilege('authenticated', 'private.app_settings', 'SELECT') or has_table_privilege('authenticated', 'private.app_settings', 'UPDATE') then
    raise exception 'FAIL  signed-in users can read or change private.app_settings';
  end if;
  raise notice 'ok    test plan switching: not callable anonymously; its on/off switch is not reachable from the API';

  select id into free_id from auth.users where email = 'free-test@modelroom.test';
  select id into plus_id from auth.users where email = 'plus-test@modelroom.test';
  if free_id is null or plus_id is null then raise exception 'FAIL  test accounts not found; run the seed step first'; end if;

  -- 3. As the Plus test user: sees their own membership, nobody else's.
  perform set_config('request.jwt.claims', json_build_object('sub', plus_id, 'role', 'authenticated')::text, true);
  set local role authenticated;
  select count(*) filter (where user_id = plus_id), count(*) filter (where user_id <> plus_id) into own, others from public.memberships;
  reset role;
  if others > 0 then raise exception 'FAIL  a signed-in user can read % other membership row(s)', others; end if;
  if own < 1 then raise exception 'FAIL  the Plus test user cannot read their own membership'; end if;
  raise notice 'ok    signed in as Plus: sees own membership (% row(s)) and no one else''s', own;

  -- 4. As the Free test user: no rows that aren't theirs.
  perform set_config('request.jwt.claims', json_build_object('sub', free_id, 'role', 'authenticated')::text, true);
  set local role authenticated;
  select count(*) into others from public.memberships where user_id <> free_id;
  reset role;
  if others > 0 then raise exception 'FAIL  the Free test user can read % other membership row(s)', others; end if;
  raise notice 'ok    signed in as Free: sees no one else''s memberships';

  -- 5. A signed-in user can't give themselves a plan.
  begin
    perform set_config('request.jwt.claims', json_build_object('sub', free_id, 'role', 'authenticated')::text, true);
    set local role authenticated;
    insert into public.memberships (user_id, tier, status, source, note) values (free_id, 'pro', 'active', 'admin', 'rls check');
    raise exception 'FAIL  a signed-in user inserted their own Pro membership' using errcode = 'P0001';
  exception
    when insufficient_privilege then raise notice 'ok    a signed-in user cannot grant themselves a plan (refused)';
  end;
  reset role;

  -- 6. Anonymous visitor (no session): refused outright.
  perform set_config('request.jwt.claims', '', true);
  begin
    set local role anon;
    select count(*) into n from public.memberships;
    reset role;
    if n > 0 then raise exception 'FAIL  anonymous visitors can read % membership row(s)', n; end if;
    raise notice 'ok    anonymous visitors see no memberships (0 rows)';
  exception
    when insufficient_privilege then raise notice 'ok    anonymous visitors are refused access to memberships (permission denied)';
  end;
  reset role;
end $$;

rollback;
