-- Read-only storage and growth snapshot of the TEST Supabase database (run daily by health-check.yml).
-- Everything is computed inside the database; only one small JSON row comes back (a few KB of egress).
-- Nothing is written, changed or deleted.
--
-- db_bytes        pg_database_size: what Supabase's 500 MB Free-plan database limit counts
-- tables          the 15 largest tables: total size (heap + indexes + TOAST), estimated rows, and, where the table has
--                 an inserted_at / created_at column, the share of its row data added in the last 7 days
--                 (growth per day ≈ total size × share_7d / 7)
-- storage_*       Supabase Storage objects (file storage, separate from the database limit)
-- audit_daily     odds.potd_model_outputs (Pick of the Day audit table) rows and row bytes per game date, last 8 days
set statement_timeout = '90s';
set default_transaction_read_only = on;
with big as (
  select c.oid, n.nspname, c.relname, pg_total_relation_size(c.oid) as bytes, greatest(c.reltuples, 0)::bigint as est_rows,
         (select a.attname from pg_attribute a
           where a.attrelid = c.oid and a.attname in ('inserted_at', 'created_at') and not a.attisdropped
           order by a.attname desc limit 1) as tcol
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where c.relkind in ('r', 'p') and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg\_%'
   order by pg_total_relation_size(c.oid) desc
   limit 15
), sized as (
  select b.nspname || '.' || b.relname as name, b.bytes, b.est_rows, b.tcol,
         case when b.tcol is null then null else
           (xpath('/row/v/text()', query_to_xml(format(
              'select coalesce(sum(pg_column_size(t.*)) filter (where t.%I >= now() - interval ''7 days''), 0)::float8'
              ' / nullif(sum(pg_column_size(t.*)), 0) as v from %I.%I t', b.tcol, b.nspname, b.relname), false, true, '')))[1]::text::float8
         end as share_7d
    from big b
)
select json_build_object(
  'checked_at', now(),
  'db_bytes', pg_database_size(current_database()),
  'tables', (select json_agg(json_build_object('name', name, 'bytes', bytes, 'est_rows', est_rows, 'time_column', tcol,
                                               'share_7d', round(share_7d::numeric, 5)) order by bytes desc) from sized),
  'storage_bytes', (select coalesce(sum((metadata->>'size')::bigint), 0) from storage.objects),
  'storage_objects', (select count(*) from storage.objects),
  'audit_daily', (select json_agg(json_build_object('game_date', d, 'rows', n, 'row_bytes', rb) order by d)
                    from (select game_date as d, count(*) as n, sum(pg_column_size(p.*)) as rb
                            from odds.potd_model_outputs p where game_date >= current_date - 8 group by 1) x)
);
