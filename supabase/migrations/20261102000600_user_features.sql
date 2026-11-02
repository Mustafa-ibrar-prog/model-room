-- Model Room: user-owned features (watchlists for Plus, alert rules for Pro)

create table public.watchlists (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles (id) on delete cascade,
  name        text not null check (char_length(name) between 1 and 60),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (user_id, name)
);
create trigger watchlists_set_updated_at
  before update on public.watchlists
  for each row execute function private.set_updated_at();

create table public.watchlist_items (
  id            uuid primary key default gen_random_uuid(),
  watchlist_id  uuid not null references public.watchlists (id) on delete cascade,
  game_id       uuid references public.games (id) on delete cascade,
  team_id       uuid references public.teams (id) on delete cascade,
  player_id     uuid references public.players (id) on delete cascade,
  created_at    timestamptz not null default now(),
  check (num_nonnulls(game_id, team_id, player_id) = 1)
);
create index watchlist_items_list_idx on public.watchlist_items (watchlist_id);
create unique index watchlist_items_unique_idx
  on public.watchlist_items (watchlist_id, coalesce(game_id, team_id, player_id));

create table public.alert_rules (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles (id) on delete cascade,
  kind        text not null check (kind in ('edge_threshold', 'line_move', 'injury_status')),
  league      public.league,
  config      jsonb not null default '{}'::jsonb check (jsonb_typeof(config) = 'object'),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index alert_rules_user_idx on public.alert_rules (user_id);
create trigger alert_rules_set_updated_at
  before update on public.alert_rules
  for each row execute function private.set_updated_at();
