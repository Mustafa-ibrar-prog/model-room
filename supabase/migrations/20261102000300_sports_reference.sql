-- Model Room: sports reference data
-- Teams, players, venues, games and historical results.
--
-- No rows are seeded here. Every factual table carries a source_id so each
-- record can be traced to the feed that supplied it; data is loaded by
-- ingestion jobs, never typed in by hand. Demo data stays in the app's demo
-- provider and is never written to these tables.

create table public.data_sources (
  id             smallint generated always as identity primary key,
  key            text not null unique check (key ~ '^[a-z0-9_]+$'),
  name           text not null,
  kind           text not null check (kind in ('schedule', 'odds', 'injuries', 'stats', 'results', 'multi')),
  homepage_url   text,
  license_notes  text,
  is_active      boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create trigger data_sources_set_updated_at
  before update on public.data_sources
  for each row execute function private.set_updated_at();

create table public.venues (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  city        text,
  region      text,
  country     text not null default 'US' check (country ~ '^[A-Z]{2}$'),
  timezone    text,
  roof        text check (roof in ('open', 'dome', 'retractable')),
  surface     text,
  latitude    numeric(8, 5) check (latitude between -90 and 90),
  longitude   numeric(8, 5) check (longitude between -180 and 180),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create trigger venues_set_updated_at
  before update on public.venues
  for each row execute function private.set_updated_at();

create table public.teams (
  id              uuid primary key default gen_random_uuid(),
  league          public.league not null,
  abbreviation    text not null check (abbreviation ~ '^[A-Z]{2,4}$'),
  location        text not null,
  nickname        text not null,
  conference      text,
  division        text,
  home_venue_id   uuid references public.venues (id) on delete set null,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (league, abbreviation),
  unique (id, league)   -- target for league-consistent foreign keys
);
create trigger teams_set_updated_at
  before update on public.teams
  for each row execute function private.set_updated_at();

create table public.players (
  id               uuid primary key default gen_random_uuid(),
  league           public.league not null,
  full_name        text not null,
  first_name       text,
  last_name        text,
  position         text,
  current_team_id  uuid,
  jersey_number    smallint check (jersey_number between 0 and 99),
  birth_date       date,
  height_in        smallint check (height_in between 48 and 100),
  weight_lb        smallint check (weight_lb between 100 and 450),
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (id, league),
  -- A player's team must be in the same league.
  foreign key (current_team_id, league) references public.teams (id, league) on delete set null (current_team_id)
);
create index players_team_idx on public.players (current_team_id);
create index players_league_name_idx on public.players (league, last_name, first_name);
create trigger players_set_updated_at
  before update on public.players
  for each row execute function private.set_updated_at();

-- Provider IDs for any entity, so ingestion can upsert by the feed's own key.
create table public.external_ids (
  source_id    smallint not null references public.data_sources (id) on delete cascade,
  entity_type  text not null check (entity_type in ('team', 'player', 'game', 'venue', 'sportsbook')),
  external_id  text not null,
  entity_id    uuid not null,
  created_at   timestamptz not null default now(),
  primary key (source_id, entity_type, external_id),
  unique (source_id, entity_type, entity_id)
);
create index external_ids_entity_idx on public.external_ids (entity_type, entity_id);

create table public.games (
  id             uuid primary key default gen_random_uuid(),
  league         public.league not null,
  season         smallint not null check (season between 1950 and 2100),
  season_type    public.season_type not null default 'regular',
  week           smallint check (week between 0 and 25),
  starts_at      timestamptz not null,
  home_team_id   uuid not null,
  away_team_id   uuid not null,
  venue_id       uuid references public.venues (id) on delete set null,
  neutral_site   boolean not null default false,
  status         public.game_status not null default 'scheduled',
  source_id      smallint not null references public.data_sources (id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (id, league),
  unique (league, home_team_id, starts_at),
  check (home_team_id <> away_team_id),
  check (league = 'nfl' or week is null),          -- weeks are an NFL concept
  check (season_type <> 'play_in' or league = 'nba'),  -- play-in is NBA only
  foreign key (home_team_id, league) references public.teams (id, league),
  foreign key (away_team_id, league) references public.teams (id, league)
);
create index games_league_starts_idx on public.games (league, starts_at);
create index games_league_season_week_idx on public.games (league, season, week);
create index games_home_team_idx on public.games (home_team_id, starts_at desc);
create index games_away_team_idx on public.games (away_team_id, starts_at desc);
create trigger games_set_updated_at
  before update on public.games
  for each row execute function private.set_updated_at();

-- Final scores. One row per completed game.
create table public.game_results (
  game_id             uuid primary key references public.games (id) on delete cascade,
  home_score          smallint not null check (home_score >= 0),
  away_score          smallint not null check (away_score >= 0),
  home_period_scores  smallint[],
  away_period_scores  smallint[],
  went_to_overtime    boolean not null default false,
  source_id           smallint not null references public.data_sources (id),
  finalized_at        timestamptz not null default now(),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  check (cardinality(home_period_scores) is not distinct from cardinality(away_period_scores))
);
create trigger game_results_set_updated_at
  before update on public.game_results
  for each row execute function private.set_updated_at();

-- Team box score per game. Stat keys vary by league, so they live in jsonb.
create table public.team_game_stats (
  game_id     uuid not null references public.games (id) on delete cascade,
  team_id     uuid not null references public.teams (id) on delete cascade,
  stats       jsonb not null default '{}'::jsonb check (jsonb_typeof(stats) = 'object'),
  source_id   smallint not null references public.data_sources (id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (game_id, team_id)
);
create trigger team_game_stats_set_updated_at
  before update on public.team_game_stats
  for each row execute function private.set_updated_at();

-- Player box score per game. Needed to grade props and train player models.
create table public.player_game_stats (
  game_id     uuid not null references public.games (id) on delete cascade,
  player_id   uuid not null references public.players (id) on delete cascade,
  team_id     uuid not null references public.teams (id) on delete cascade,
  did_play    boolean not null default true,
  minutes     numeric(5, 2) check (minutes >= 0),
  stats       jsonb not null default '{}'::jsonb check (jsonb_typeof(stats) = 'object'),
  source_id   smallint not null references public.data_sources (id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (game_id, player_id)
);
create index player_game_stats_player_idx on public.player_game_stats (player_id);
create trigger player_game_stats_set_updated_at
  before update on public.player_game_stats
  for each row execute function private.set_updated_at();
