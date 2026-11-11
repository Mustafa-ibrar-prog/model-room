-- Sportsbook line snapshots for the TEST SITE (The Odds API, collected at the 7 AM / noon PT refreshes).
--
-- Why here and not in the repository: the repository is public, and The Odds API's terms allow storing and displaying
-- the data but not offering it as downloadable files. This schema is not exposed through the Supabase API (only
-- the GitHub Actions workflow reads and writes it, over the database connection) and API roles have no access.
--
-- Append-only: rows can be inserted, never updated or deleted (triggers below). Each league's rows form a hash
-- chain: row_hash = sha256(prev_hash || payload), payload = the canonical JSON of the snapshot exactly as collected.
-- `python -m modelroom odds-store verify` recomputes the chain and checks every typed column against its payload.

create schema if not exists odds;
revoke all on schema odds from public, anon, authenticated;

create table if not exists odds.snapshots (
  id            bigint generated always as identity primary key,
  league        text not null check (league in ('nba', 'nfl')),
  seq           bigint not null check (seq >= 1),
  content_key   text not null,
  payload       text not null,
  prev_hash     text not null check (prev_hash ~ '^[0-9a-f]{64}$'),
  row_hash      text not null check (row_hash ~ '^[0-9a-f]{64}$'),
  batch         text not null,
  run_id        text,
  raw_sha256    text check (raw_sha256 is null or raw_sha256 ~ '^[0-9a-f]{64}$'),
  inserted_at   timestamptz not null default now(),
  -- typed copies of payload fields, for queries (verified against payload)
  game_id       text,
  home_team     text not null,
  away_team     text not null,
  commence_time timestamptz not null,
  sportsbook    text not null,
  market        text not null check (market in ('spread', 'total', 'moneyline')),
  line          double precision,
  home_price    double precision,
  away_price    double precision,
  over_price    double precision,
  under_price   double precision,
  captured_at   timestamptz,
  collected_at  timestamptz,
  source        text not null,
  unique (league, seq),
  unique (league, content_key),
  unique (row_hash)
);
revoke all on table odds.snapshots from public, anon, authenticated;
alter table odds.snapshots enable row level security;  -- no policies: invisible to API roles
comment on table odds.snapshots is 'Model Room TEST: append-only, hash-chained sportsbook line snapshots (never updated or deleted).';

create index if not exists snapshots_game_idx on odds.snapshots (league, game_id, sportsbook, market, collected_at);
create index if not exists snapshots_collected_idx on odds.snapshots (league, collected_at);

create or replace function odds.refuse_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'odds.snapshots is append-only: % is not allowed', tg_op;
end;
$$;

drop trigger if exists snapshots_no_update on odds.snapshots;
create trigger snapshots_no_update before update or delete on odds.snapshots
  for each row execute function odds.refuse_change();
drop trigger if exists snapshots_no_truncate on odds.snapshots;
create trigger snapshots_no_truncate before truncate on odds.snapshots
  for each statement execute function odds.refuse_change();
