-- owner_reader permission checks. Run as a superuser on a scratch database after all migrations
-- (never against Supabase). Every check raises on failure; success prints one line per check.

-- 1. Exactly four readable objects, and no write privilege anywhere.
do $$
declare readable text[]; writable text[];
begin
  select array_agg(n.nspname || '.' || c.relname order by n.nspname, c.relname) into readable
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where c.relkind in ('r', 'v', 'm', 'p', 'f')
    and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg_toast%'
    and has_table_privilege('owner_reader', c.oid, 'SELECT');
  if readable is distinct from array['odds.comparisons', 'odds.reports', 'odds.snapshots', 'scheduler.health'] then
    raise exception 'owner_reader can read %', readable;
  end if;
  select array_agg(n.nspname || '.' || c.relname) into writable
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where c.relkind in ('r', 'v', 'm', 'p', 'f')
    and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg_toast%'
    and (has_table_privilege('owner_reader', c.oid, 'INSERT') or has_table_privilege('owner_reader', c.oid, 'UPDATE')
         or has_table_privilege('owner_reader', c.oid, 'DELETE') or has_table_privilege('owner_reader', c.oid, 'TRUNCATE')
         or has_table_privilege('owner_reader', c.oid, 'REFERENCES') or has_table_privilege('owner_reader', c.oid, 'TRIGGER'));
  if writable is not null then raise exception 'owner_reader can write %', writable; end if;
  raise notice 'ok  reads exactly odds.snapshots, odds.comparisons, odds.reports, scheduler.health; writes nothing';
end $$;

-- 2. No CREATE on any schema; not a superuser, no role or database creation, no login until the owner sets a password.
do $$
declare s text;
begin
  select string_agg(nspname, ', ') into s from pg_namespace
  where nspname not like 'pg_%' and nspname <> 'information_schema' and has_schema_privilege('owner_reader', oid, 'CREATE');
  if s is not null then raise exception 'owner_reader can create in %', s; end if;
  if exists (select 1 from pg_roles where rolname = 'owner_reader' and (rolsuper or rolcreaterole or rolcreatedb or rolreplication or rolbypassrls)) then
    raise exception 'owner_reader has elevated attributes';
  end if;
  if exists (select 1 from pg_roles where rolname = 'owner_reader' and rolcanlogin) then
    raise exception 'owner_reader can log in straight from the migration (the owner sets the password)';
  end if;
  if not exists (select 1 from pg_db_role_setting s join pg_roles r on r.oid = s.setrole
                 where r.rolname = 'owner_reader' and 'default_transaction_read_only=on' = any(s.setconfig)) then
    raise exception 'owner_reader sessions are not read-only by default';
  end if;
  raise notice 'ok  no CREATE anywhere, no elevated attributes, no login until a password is set, read-only sessions';
end $$;

-- 3. As owner_reader: the four objects read (row security allows it), every write is refused.
alter role owner_reader with login password 'local-test-only';
insert into odds.comparisons (league, seq, content_key, payload, prev_hash, row_hash, batch)
  values ('nba', 1, 'k', '{}', repeat('0', 64), repeat('a', 64), 'test');
set role owner_reader;
do $$
declare n int;
begin
  select count(*) into n from odds.comparisons;
  if n <> 1 then raise exception 'owner_reader sees % comparisons, expected 1 (row security)', n; end if;
  perform count(*) from odds.snapshots; perform count(*) from odds.reports; perform * from scheduler.health;
  begin insert into odds.comparisons (league, seq, content_key, payload, prev_hash, row_hash, batch)
          values ('nba', 2, 'x', '{}', repeat('0', 64), repeat('b', 64), 'x');
        raise exception 'insert was allowed';
  exception when insufficient_privilege or read_only_sql_transaction then null; end;
  begin delete from odds.reports; raise exception 'delete was allowed';
  exception when insufficient_privilege or read_only_sql_transaction then null; end;
  begin perform 1 from scheduler.dispatch_log; raise exception 'scheduler.dispatch_log readable';
  exception when insufficient_privilege then null; end;
  begin perform 1 from private.app_settings; raise exception 'private.app_settings readable';
  exception when insufficient_privilege then null; end;
  begin create table public.x (i int); raise exception 'create table was allowed';
  exception when insufficient_privilege or read_only_sql_transaction then null; end;
  raise notice 'ok  as owner_reader: reads the four objects; insert, delete, other schemas and create are refused';
end $$;
reset role;
alter role owner_reader with nologin password null;
