-- TEST ONLY. Never run against a Supabase project.
--
-- Recreates the parts of Supabase that the migrations depend on, so they can
-- be tested on a plain Postgres 15+ server: the anon / authenticated /
-- service_role roles, the auth schema with auth.users and auth.uid(), and
-- Supabase's default grants on the public schema.

create role anon nologin noinherit;
create role authenticated nologin noinherit;
create role service_role nologin noinherit bypassrls;

create schema auth;
grant usage on schema auth to anon, authenticated, service_role;

create table auth.users (
  id     uuid primary key default gen_random_uuid(),
  email  text,
  raw_user_meta_data jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

-- Same claim lookup Supabase uses.
create function auth.uid() returns uuid language sql stable as $$
  select nullif(
    coalesce(
      current_setting('request.jwt.claim.sub', true),
      (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    ), ''
  )::uuid
$$;

create function auth.role() returns text language sql stable as $$
  select coalesce(
    current_setting('request.jwt.claim.role', true),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )
$$;

grant execute on function auth.uid(), auth.role() to anon, authenticated, service_role;

-- Supabase's defaults: client roles get broad privileges on public objects,
-- and RLS is what restricts them. The migrations must revoke these.
grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables    to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
