-- Read-only projection for the R2 archive dry run (TEST; Moose 2026-11-24). Computed in the database; one small JSON
-- row back. Nothing is written, changed or deleted.
--
-- For each hash-chained odds table and league: rows, highest seq, how many rows fall in CLOSED archive segments
-- (whole blocks of SEGMENT_ROWS: snapshots 2000, comparisons 10000, reports 25, as modelroom/archive/odds.py), the open
-- tail that would stay in Supabase, and the share of the table's row data in closed segments. For the Pick of the Day
-- audit table: rows and row-data share in closed days (game_date at least 2 days old, as archive/audit.py).
-- Projected storage that COULD be freed = table size x closed share. Freeing it would need deleting source rows, which
-- is not part of this dry run and needs separate approval.
set statement_timeout = '120s';
set default_transaction_read_only = on;
with seg(tbl, n) as (values ('snapshots', 2000), ('comparisons', 10000), ('reports', 25)),
t as (
  select s.tbl, x.league, x.rows, x.max_seq, (x.max_seq / s.n) * s.n as closed_seq, s.n,
         pg_total_relation_size(format('odds.%I', s.tbl)::regclass) as table_bytes
    from seg s
    cross join lateral (
      select (xpath('/row/league/text()', r))[1]::text as league, (xpath('/row/rows/text()', r))[1]::text::bigint as rows,
             (xpath('/row/max_seq/text()', r))[1]::text::bigint as max_seq
        from unnest(xpath('/table/row', query_to_xml(format('select league, count(*) as rows, max(seq) as max_seq from odds.%I group by league', s.tbl), false, false, ''))) r
    ) x
),
sh as (
  select t.*, (xpath('/row/v/text()', query_to_xml(format(
           'select coalesce(sum(pg_column_size(p.*)) filter (where p.seq <= %s), 0)::float8 / nullif(sum(pg_column_size(p.*)), 0) as v'
           ' from odds.%I p where p.league = %L', t.closed_seq, t.tbl, t.league), false, true, '')))[1]::text::float8 as closed_share_league,
         (xpath('/row/v/text()', query_to_xml(format(
           'select coalesce(sum(pg_column_size(p.*)) filter (where p.league = %L), 0)::float8 / nullif(sum(pg_column_size(p.*)), 0) as v'
           ' from odds.%I p', t.league, t.tbl), false, true, '')))[1]::text::float8 as league_share
    from t
)
select json_build_object(
  'checked_at', now(),
  'db_bytes', pg_database_size(current_database()),
  'odds', (select json_agg(json_build_object('table', tbl, 'league', league, 'rows', rows, 'max_seq', max_seq, 'segment_rows', n,
                   'closed_rows', closed_seq, 'tail_rows', rows - closed_seq, 'table_bytes', table_bytes,
                   'closed_share', round((coalesce(closed_share_league, 0) * coalesce(league_share, 0))::numeric, 5)) order by tbl, league) from sh),
  'audit', (select json_build_object('rows', count(*), 'closed_rows', count(*) filter (where game_date <= current_date - 2),
                   'table_bytes', pg_total_relation_size('odds.potd_model_outputs'::regclass),
                   'closed_share', round((coalesce(sum(pg_column_size(p.*)) filter (where game_date <= current_date - 2), 0)::float8
                                          / nullif(sum(pg_column_size(p.*)), 0))::numeric, 5))
              from odds.potd_model_outputs p)
);
