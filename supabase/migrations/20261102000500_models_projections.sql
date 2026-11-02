-- Model Room: model versions, ratings, projections and graded results
--
-- Projections are split by plan: each table maps to one entitlement feature,
-- so RLS can gate whole rows instead of individual columns.
--
--   team_ratings                     ratings.overall        Free
--   team_rating_components           ratings.advanced       Pro
--   game_projections                 games.basicProjections Free
--   game_projection_details          games.projectedScores  Plus
--   injury_impacts                   injuries.adjustments   Plus
--   player_projections               props.projections      Plus
--   player_projection_distributions  props.advanced         Pro
--   prediction_results               history                Pro
--
-- A projection only becomes visible to users once published_at is set, and
-- it can only be published if its model version is 'validated'. Unverified
-- models can write rows for backtesting, but users never see them.

create table public.model_versions (
  id            uuid primary key default gen_random_uuid(),
  league        public.league not null,
  engine        public.model_engine not null,
  version       text not null check (version ~ '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'),
  status        public.model_status not null default 'development',
  description   text,
  code_ref      text,          -- git commit of the engine that produced it
  validated_at  timestamptz,
  validated_by  uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (league, engine, version),
  check (status <> 'validated' or validated_at is not null)
);
create trigger model_versions_set_updated_at
  before update on public.model_versions
  for each row execute function private.set_updated_at();

-- Blocks publishing output from a model that has not been validated.
create function private.require_validated_model()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.published_at is not null and not exists (
    select 1 from public.model_versions mv
    where mv.id = new.model_version_id and mv.status in ('validated', 'retired')
  ) then
    raise exception 'Cannot publish output from model version % because it is not validated.', new.model_version_id
      using errcode = '23514';
  end if;
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Team ratings
-- ---------------------------------------------------------------------------
create table public.team_ratings (
  id                uuid primary key default gen_random_uuid(),
  team_id           uuid not null references public.teams (id) on delete cascade,
  model_version_id  uuid not null references public.model_versions (id),
  as_of             timestamptz not null,
  overall           numeric(6, 2) not null,   -- points vs an average team, neutral field
  published_at      timestamptz,
  created_at        timestamptz not null default now(),
  unique (team_id, model_version_id, as_of)
);
create index team_ratings_lookup_idx on public.team_ratings (team_id, as_of desc);
create trigger team_ratings_require_validated
  before insert or update of published_at on public.team_ratings
  for each row execute function private.require_validated_model();

create table public.team_rating_components (
  team_rating_id     uuid primary key references public.team_ratings (id) on delete cascade,
  offense            numeric(7, 2) not null,
  defense            numeric(7, 2) not null,
  pace               numeric(6, 2),
  schedule_strength  numeric(6, 2)
);

-- ---------------------------------------------------------------------------
-- Game projections
-- ---------------------------------------------------------------------------
create table public.game_projections (
  id                          uuid primary key default gen_random_uuid(),
  game_id                     uuid not null references public.games (id) on delete cascade,
  model_version_id            uuid not null references public.model_versions (id),
  generated_at                timestamptz not null,
  model_spread_home           numeric(5, 2) not null,  -- negative = home favored
  model_total                 numeric(6, 2) not null check (model_total > 0),
  market_spread_at_generation numeric(5, 1),
  market_total_at_generation  numeric(5, 1),
  inputs_hash                 text,                     -- reproducibility check for backtests
  published_at                timestamptz,
  created_at                  timestamptz not null default now(),
  unique (game_id, model_version_id, generated_at)
);
create index game_projections_game_idx on public.game_projections (game_id, generated_at desc);
create index game_projections_published_idx on public.game_projections (published_at) where published_at is not null;
create trigger game_projections_require_validated
  before insert or update of published_at on public.game_projections
  for each row execute function private.require_validated_model();

create table public.game_projection_details (
  game_projection_id    uuid primary key references public.game_projections (id) on delete cascade,
  projected_home_score  numeric(6, 2) not null check (projected_home_score >= 0),
  projected_away_score  numeric(6, 2) not null check (projected_away_score >= 0),
  home_win_probability  numeric(5, 4) check (home_win_probability between 0 and 1),
  matchup_note          text check (char_length(matchup_note) <= 600)
);

-- How far a specific absence moves a game's line.
create table public.injury_impacts (
  id                 uuid primary key default gen_random_uuid(),
  injury_report_id   uuid not null references public.injury_reports (id) on delete cascade,
  game_id            uuid references public.games (id) on delete cascade,
  model_version_id   uuid not null references public.model_versions (id),
  spread_impact      numeric(5, 2) not null,
  total_impact       numeric(5, 2) not null,
  generated_at       timestamptz not null,
  published_at       timestamptz,
  created_at         timestamptz not null default now(),
  unique (injury_report_id, model_version_id, generated_at)
);
create index injury_impacts_game_idx on public.injury_impacts (game_id);
create trigger injury_impacts_require_validated
  before insert or update of published_at on public.injury_impacts
  for each row execute function private.require_validated_model();

-- ---------------------------------------------------------------------------
-- Player projections (props)
-- ---------------------------------------------------------------------------
create table public.player_projections (
  id                        uuid primary key default gen_random_uuid(),
  game_id                   uuid not null references public.games (id) on delete cascade,
  player_id                 uuid not null references public.players (id) on delete cascade,
  model_version_id          uuid not null references public.model_versions (id),
  prop_market_key           text not null references public.prop_markets (key),
  projection                numeric(7, 2) not null,
  market_line_at_generation numeric(6, 1),
  generated_at              timestamptz not null,
  published_at              timestamptz,
  created_at                timestamptz not null default now(),
  unique (game_id, player_id, prop_market_key, model_version_id, generated_at)
);
create index player_projections_game_idx on public.player_projections (game_id, prop_market_key);
create index player_projections_player_idx on public.player_projections (player_id, generated_at desc);
create trigger player_projections_require_validated
  before insert or update of published_at on public.player_projections
  for each row execute function private.require_validated_model();

create table public.player_projection_distributions (
  player_projection_id  uuid primary key references public.player_projections (id) on delete cascade,
  over_share            numeric(5, 4) check (over_share between 0 and 1),
  range_low             numeric(7, 2),
  range_high            numeric(7, 2),
  percentiles           jsonb check (percentiles is null or jsonb_typeof(percentiles) = 'object'),
  check (range_low is null or range_high is null or range_low <= range_high)
);

-- ---------------------------------------------------------------------------
-- Graded predictions and model performance
-- ---------------------------------------------------------------------------
create table public.prediction_results (
  id                    uuid primary key default gen_random_uuid(),
  kind                  public.prediction_kind not null,
  game_projection_id    uuid references public.game_projections (id) on delete cascade,
  player_projection_id  uuid references public.player_projections (id) on delete cascade,
  model_version_id      uuid not null references public.model_versions (id),
  game_id               uuid not null references public.games (id) on delete cascade,
  market_line           numeric(6, 1) not null,   -- line the edge was measured against
  model_value           numeric(7, 2) not null,
  closing_line          numeric(6, 1),
  actual_value          numeric(7, 2) not null,
  edge                  numeric(6, 2) not null,
  closing_line_value    numeric(6, 2),
  outcome               public.prediction_outcome not null,
  graded_at             timestamptz not null default now(),
  created_at            timestamptz not null default now(),
  constraint prediction_results_target check (
    (kind in ('game_spread', 'game_total') and game_projection_id is not null and player_projection_id is null)
 or (kind = 'player_prop' and player_projection_id is not null and game_projection_id is null)
  ),
  unique (kind, game_projection_id),
  unique (player_projection_id)
);
create index prediction_results_model_idx on public.prediction_results (model_version_id, graded_at desc);
create index prediction_results_game_idx on public.prediction_results (game_id);

create view public.model_performance
with (security_invoker = true) as
select
  pr.model_version_id,
  mv.league,
  mv.engine,
  mv.version,
  pr.kind,
  count(*)                                                    as graded,
  count(*) filter (where pr.outcome = 'win')                  as wins,
  count(*) filter (where pr.outcome = 'loss')                 as losses,
  count(*) filter (where pr.outcome = 'push')                 as pushes,
  round(
    count(*) filter (where pr.outcome = 'win')::numeric
    / nullif(count(*) filter (where pr.outcome in ('win', 'loss')), 0), 4
  )                                                           as win_rate,
  round(avg(pr.closing_line_value), 3)                        as avg_closing_line_value,
  min(pr.graded_at)                                           as first_graded_at,
  max(pr.graded_at)                                           as last_graded_at
from public.prediction_results pr
join public.model_versions mv on mv.id = pr.model_version_id
group by pr.model_version_id, mv.league, mv.engine, mv.version, pr.kind;

-- ---------------------------------------------------------------------------
-- Daily insights (editorial notes, Free)
-- ---------------------------------------------------------------------------
create table public.daily_insights (
  id            uuid primary key default gen_random_uuid(),
  league        public.league not null,
  title         text not null check (char_length(title) <= 120),
  body          text not null check (char_length(body) <= 1200),
  game_id       uuid references public.games (id) on delete set null,
  publish_date  date not null,
  author_id     uuid references public.profiles (id) on delete set null,
  published_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index daily_insights_date_idx on public.daily_insights (publish_date desc) where published_at is not null;
create trigger daily_insights_set_updated_at
  before update on public.daily_insights
  for each row execute function private.set_updated_at();
