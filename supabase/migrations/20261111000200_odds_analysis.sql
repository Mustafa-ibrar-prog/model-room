-- Sportsbook analysis records for the TEST SITE (private, append-only, hash-chained like odds.snapshots).
--
-- odds.comparisons  one row per sportsbook snapshot side matched to the latest Model Room game prediction recorded
--                   before that snapshot was collected: the book's line and prices, implied probabilities with and
--                   without the bookmaker margin, and the model's probability at that exact line. Written once,
--                   never changed. Unvalidated comparisons; outcomes are evaluated separately once games settle.
-- odds.reports      one row per analysis run and league: the detailed report (line histories, movement, coverage,
--                   missing and stale lines, settled-game evaluation). Kept private because it contains sportsbook
--                   lines; the public repository only gets aggregate counts.
--
-- Both tables: payload = canonical JSON; row_hash = sha256(prev_hash || payload) per league; UPDATE, DELETE and
-- TRUNCATE refused; not reachable by API roles. Verified by `python -m modelroom odds-store verify`.

create table if not exists odds.comparisons (
  id           bigint generated always as identity primary key,
  league       text not null check (league in ('nba', 'nfl')),
  seq          bigint not null check (seq >= 1),
  content_key  text not null,
  payload      text not null,
  prev_hash    text not null check (prev_hash ~ '^[0-9a-f]{64}$'),
  row_hash     text not null check (row_hash ~ '^[0-9a-f]{64}$'),
  batch        text not null,
  run_id       text,
  inserted_at  timestamptz not null default now(),
  unique (league, seq),
  unique (league, content_key),
  unique (row_hash)
);

create table if not exists odds.reports (
  id           bigint generated always as identity primary key,
  league       text not null check (league in ('nba', 'nfl')),
  seq          bigint not null check (seq >= 1),
  content_key  text not null,
  payload      text not null,
  prev_hash    text not null check (prev_hash ~ '^[0-9a-f]{64}$'),
  row_hash     text not null check (row_hash ~ '^[0-9a-f]{64}$'),
  batch        text not null,
  run_id       text,
  inserted_at  timestamptz not null default now(),
  unique (league, seq),
  unique (league, content_key),
  unique (row_hash)
);

revoke all on table odds.comparisons, odds.reports from public, anon, authenticated;
alter table odds.comparisons enable row level security;
alter table odds.reports enable row level security;
comment on table odds.comparisons is 'Model Room TEST: append-only model-vs-sportsbook comparisons at matching timestamps (unvalidated; never updated or deleted).';
comment on table odds.reports is 'Model Room TEST: append-only sportsbook analysis reports per run and league (never updated or deleted).';

drop trigger if exists comparisons_no_update on odds.comparisons;
create trigger comparisons_no_update before update or delete on odds.comparisons
  for each row execute function odds.refuse_change();
drop trigger if exists comparisons_no_truncate on odds.comparisons;
create trigger comparisons_no_truncate before truncate on odds.comparisons
  for each statement execute function odds.refuse_change();
drop trigger if exists reports_no_update on odds.reports;
create trigger reports_no_update before update or delete on odds.reports
  for each row execute function odds.refuse_change();
drop trigger if exists reports_no_truncate on odds.reports;
create trigger reports_no_truncate before truncate on odds.reports
  for each statement execute function odds.refuse_change();
