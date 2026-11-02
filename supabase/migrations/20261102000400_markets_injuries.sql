-- Model Room: betting markets, line movement and injury reports

create table public.sportsbooks (
  id          smallint generated always as identity primary key,
  key         text not null unique check (key ~ '^[a-z0-9_]+$'),
  name        text not null,
  region      text not null default 'us',
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- Prop market taxonomy (for example 'nfl.passing_yards'). Categories only.
create table public.prop_markets (
  key         text primary key check (key ~ '^(nfl|nba)\.[a-z0-9_]+$'),
  league      public.league not null,
  label       text not null,
  unit        text not null,
  created_at  timestamptz not null default now(),
  check (split_part(key, '.', 1) = league::text)
);

-- American odds are <= -100 or >= +100.
create function private.is_american_price(p integer)
returns boolean
language sql
immutable
set search_path = ''
as $$ select p is null or p <= -100 or p >= 100 $$;
grant execute on function private.is_american_price(integer) to anon, authenticated, service_role;

-- Every captured game line. The full history is line movement (Plus).
-- Spreads are stored from the home side: negative = home favored.
create table public.odds_snapshots (
  id             bigint generated always as identity primary key,
  game_id        uuid not null references public.games (id) on delete cascade,
  sportsbook_id  smallint not null references public.sportsbooks (id),
  market         public.odds_market not null,
  line           numeric(5, 1),
  home_price     integer check (private.is_american_price(home_price)),
  away_price     integer check (private.is_american_price(away_price)),
  over_price     integer check (private.is_american_price(over_price)),
  under_price    integer check (private.is_american_price(under_price)),
  is_opening     boolean not null default false,
  is_closing     boolean not null default false,
  captured_at    timestamptz not null,
  source_id      smallint not null references public.data_sources (id),
  created_at     timestamptz not null default now(),
  unique (game_id, sportsbook_id, market, captured_at),
  constraint odds_snapshots_market_shape check (
    (market = 'spread'    and line is not null and over_price is null and under_price is null)
 or (market = 'total'     and line > 0         and home_price is null and away_price is null)
 or (market = 'moneyline' and line is null     and over_price is null and under_price is null
                          and home_price is not null and away_price is not null)
  )
);
create index odds_snapshots_game_market_idx on public.odds_snapshots (game_id, market, captured_at desc);
create unique index odds_snapshots_one_opening_idx
  on public.odds_snapshots (game_id, sportsbook_id, market) where is_opening;
create unique index odds_snapshots_one_closing_idx
  on public.odds_snapshots (game_id, sportsbook_id, market) where is_closing;

-- Latest line per game, book and market. Maintained by trigger so the
-- current market can be public while the history stays gated.
create table public.market_lines_current (
  game_id         uuid not null references public.games (id) on delete cascade,
  sportsbook_id   smallint not null references public.sportsbooks (id),
  market          public.odds_market not null,
  line            numeric(5, 1),
  home_price      integer,
  away_price      integer,
  over_price      integer,
  under_price     integer,
  snapshot_id     bigint not null references public.odds_snapshots (id) on delete cascade,
  captured_at     timestamptz not null,
  primary key (game_id, sportsbook_id, market)
);
create index market_lines_current_game_idx on public.market_lines_current (game_id);

create function private.refresh_market_line_current()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.market_lines_current as cur
    (game_id, sportsbook_id, market, line, home_price, away_price, over_price, under_price, snapshot_id, captured_at)
  values
    (new.game_id, new.sportsbook_id, new.market, new.line, new.home_price, new.away_price,
     new.over_price, new.under_price, new.id, new.captured_at)
  on conflict (game_id, sportsbook_id, market) do update
    set line = excluded.line,
        home_price = excluded.home_price,
        away_price = excluded.away_price,
        over_price = excluded.over_price,
        under_price = excluded.under_price,
        snapshot_id = excluded.snapshot_id,
        captured_at = excluded.captured_at
    where cur.captured_at <= excluded.captured_at;
  return new;
end;
$$;

create trigger odds_snapshots_refresh_current
  after insert on public.odds_snapshots
  for each row execute function private.refresh_market_line_current();

-- Player prop lines from books. Prop data: Plus and above.
create table public.player_prop_odds (
  id               bigint generated always as identity primary key,
  game_id          uuid not null references public.games (id) on delete cascade,
  player_id        uuid not null references public.players (id) on delete cascade,
  sportsbook_id    smallint not null references public.sportsbooks (id),
  prop_market_key  text not null references public.prop_markets (key),
  line             numeric(6, 1) not null,
  over_price       integer check (private.is_american_price(over_price)),
  under_price      integer check (private.is_american_price(under_price)),
  is_closing       boolean not null default false,
  captured_at      timestamptz not null,
  source_id        smallint not null references public.data_sources (id),
  created_at       timestamptz not null default now(),
  unique (game_id, player_id, sportsbook_id, prop_market_key, captured_at)
);
create index player_prop_odds_lookup_idx
  on public.player_prop_odds (game_id, player_id, prop_market_key, captured_at desc);

-- Injury reports. Each status change is a new row, so history is kept.
create table public.injury_reports (
  id           uuid primary key default gen_random_uuid(),
  league       public.league not null,
  player_id    uuid not null,
  team_id      uuid not null,
  game_id      uuid references public.games (id) on delete set null,
  status       public.injury_status not null,
  description  text check (char_length(description) <= 200),
  reported_at  timestamptz not null,
  source_id    smallint not null references public.data_sources (id),
  created_at   timestamptz not null default now(),
  unique (player_id, reported_at, source_id),
  foreign key (player_id, league) references public.players (id, league) on delete cascade,
  foreign key (team_id, league) references public.teams (id, league) on delete cascade
);
create index injury_reports_player_idx on public.injury_reports (player_id, reported_at desc);
create index injury_reports_team_idx on public.injury_reports (team_id, reported_at desc);
create index injury_reports_game_idx on public.injury_reports (game_id) where game_id is not null;

-- Latest report per player. security_invoker keeps the caller's RLS.
create view public.current_injuries
with (security_invoker = true) as
select distinct on (ir.player_id) ir.*
from public.injury_reports ir
order by ir.player_id, ir.reported_at desc;
