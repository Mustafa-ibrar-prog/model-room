-- NBA Pick of the Day audit trail for the TEST SITE (private, append-only). Approved by Moose 2026-11-22.
--
-- odds.potd_model_outputs  one row per player, eligible stat (points, rebounds, assists, threes) and published active
--                          board: Model Room's OWN outputs only. Player, stat, the model's side and probability against
--                          a model-independent reference (his own season average from box scores), the projection,
--                          model version, params hash, timestamps and the model-derived explanation.
--
-- Never stored here: Polymarket (or any market) prices, lines, probabilities, edges, or market-derived qualification /
-- rejection decisions, and these rows cannot grade Polymarket contracts (no authorized grading reference is kept).
-- UPDATE, DELETE and TRUNCATE refused; not reachable by API roles (same as odds.snapshots).

create table if not exists odds.potd_model_outputs (
  id                  bigint generated always as identity primary key,
  game_date           date not null,
  game_id             text not null,
  game_start          timestamptz,
  player_id           text not null,
  player              text not null,
  team                text,
  opp                 text,
  stat                text not null check (stat in ('points', 'rebounds', 'assists', 'threes')),
  model_version       text not null,
  params_hash         text,
  board_generated_at  timestamptz not null,
  projection          double precision not null,
  reference           text not null,
  reference_value     double precision,
  model_side          text check (model_side in ('over', 'under')),
  model_prob          double precision check (model_prob between 0 and 1),
  explanation         text not null,
  contributions       jsonb,
  run_id              text,
  inserted_at         timestamptz not null default now(),
  unique (game_id, player_id, stat, model_version, board_generated_at)
);

revoke all on table odds.potd_model_outputs from public, anon, authenticated;
alter table odds.potd_model_outputs enable row level security;
comment on table odds.potd_model_outputs is 'Model Room TEST: private audit of NBA Pick of the Day model outputs (model data only; no market prices, lines or decisions; never updated or deleted).';

drop trigger if exists potd_outputs_no_update on odds.potd_model_outputs;
create trigger potd_outputs_no_update before update or delete on odds.potd_model_outputs
  for each row execute function odds.refuse_change();
drop trigger if exists potd_outputs_no_truncate on odds.potd_model_outputs;
create trigger potd_outputs_no_truncate before truncate on odds.potd_model_outputs
  for each statement execute function odds.refuse_change();
