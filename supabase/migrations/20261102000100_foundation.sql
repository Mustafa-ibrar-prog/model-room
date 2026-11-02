-- Model Room: foundation
-- Shared types, the private schema for security helpers, and timestamp triggers.

-- The `private` schema is NOT exposed through the Supabase Data API (only
-- `public` and `graphql_public` are, see supabase/config.toml). Security
-- helpers live here so they can be used inside RLS policies but never called
-- directly over REST with arbitrary arguments.
create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to anon, authenticated, service_role;

-- Leagues Model Room covers.
create type public.league as enum ('nfl', 'nba');

-- Membership tiers. Declaration order matters: free < plus < pro, so tiers can
-- be compared with >= in SQL. Must match TIER_ORDER in src/config/tiers.ts.
create type public.membership_tier as enum ('free', 'plus', 'pro');

create type public.membership_status as enum (
  'active',     -- paid and current
  'trialing',   -- in a free trial period
  'past_due',   -- payment failed, inside the retry/grace window
  'paused',     -- paused by the customer or merchant
  'cancelled',  -- cancelled; access ends at current_period_end
  'expired'     -- ended
);

create type public.membership_source as enum (
  'shopify', -- driven by a Shopify subscription contract
  'admin'    -- granted manually by a Model Room administrator
);

create type public.app_role as enum ('admin');

create type public.season_type as enum ('preseason', 'regular', 'play_in', 'postseason');

create type public.game_status as enum (
  'scheduled', 'in_progress', 'final', 'postponed', 'suspended', 'cancelled'
);

create type public.injury_status as enum (
  'out', 'doubtful', 'questionable', 'probable', 'day_to_day',
  'injured_reserve', 'suspended', 'active'
);

create type public.odds_market as enum ('spread', 'total', 'moneyline');

create type public.model_engine as enum ('game', 'team_ratings', 'injury_impact', 'player_props');

create type public.model_status as enum (
  'development', -- may not be published to users
  'validated',   -- backtested and approved; projections may be published
  'retired'      -- no new projections; history stays readable
);

create type public.prediction_kind as enum ('game_spread', 'game_total', 'player_prop');

create type public.prediction_outcome as enum ('win', 'loss', 'push', 'no_action');

-- Keeps updated_at current on every UPDATE.
create function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- Postgres grants EXECUTE on new functions to PUBLIC by default. Model Room
-- grants function access explicitly instead.
alter default privileges in schema public revoke execute on functions from public;
alter default privileges in schema private revoke execute on functions from public;
