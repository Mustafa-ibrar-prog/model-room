-- Archive index for the TEST SITE's private Cloudflare R2 archive (Moose, 2026-11-23). One row per archived object, so
-- the application finds historical data without listing the bucket. Pointers and checksums only: no payloads, no
-- market data, no credentials. Append-only (same guard as the odds tables); not reachable by API roles.
create schema if not exists archive;
revoke all on schema archive from public, anon, authenticated;

create table if not exists archive.objects (
  id               bigint generated always as identity primary key,
  dataset          text not null,               -- 'odds.reports', 'odds.comparisons', 'odds.snapshots', 'ledger', 'audit.potd_model_outputs'
  league           text,
  object_key       text not null,               -- path inside the private bucket
  seq_first        bigint,
  seq_last         bigint,
  rows             bigint not null,
  first_prev_hash  text,
  last_row_hash    text,
  date_first       timestamptz,
  date_last        timestamptz,
  bytes            bigint not null,
  sha256           text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  format           text not null,
  run_id           text,
  created_at       timestamptz not null default now(),
  unique (object_key, sha256)
);
revoke all on table archive.objects from public, anon, authenticated;
alter table archive.objects enable row level security;
comment on table archive.objects is 'Model Room TEST: index of objects in the private R2 archive (pointers and checksums only; never updated or deleted).';

drop trigger if exists archive_objects_no_update on archive.objects;
create trigger archive_objects_no_update before update or delete on archive.objects
  for each row execute function odds.refuse_change();
drop trigger if exists archive_objects_no_truncate on archive.objects;
create trigger archive_objects_no_truncate before truncate on archive.objects
  for each statement execute function odds.refuse_change();
