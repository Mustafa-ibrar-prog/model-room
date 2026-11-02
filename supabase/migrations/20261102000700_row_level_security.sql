-- Model Room: Row Level Security
--
-- Principles
--   1. Deny by default. All table privileges are revoked from anon and
--      authenticated, RLS is enabled on every table, then access is granted
--      back table by table.
--   2. Plan checks call private.has_feature(), which reads tier_features, the
--      database copy of src/lib/entitlements.ts.
--   3. Nobody but the service role writes memberships, roles, identities,
--      sports data or projections. Admins change memberships only through
--      admin_grant_membership() / admin_end_membership().
--   4. The service role bypasses RLS. Its key lives only in server env vars.

-- ---------------------------------------------------------------------------
-- 1. Deny by default
-- ---------------------------------------------------------------------------
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

grant usage on schema public to anon, authenticated, service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;

-- Supabase's default privileges let anon and authenticated execute every
-- function in public. Revoke all of it, then grant back an explicit list.
revoke execute on all functions in schema public  from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon, authenticated;
alter default privileges in schema public  revoke execute on functions from anon, authenticated;
alter default privileges in schema private revoke execute on functions from anon, authenticated;
grant execute on all functions in schema public  to service_role;
grant execute on all functions in schema private to service_role;

-- Caller-scoped helpers used inside policies, checks and triggers.
grant execute on function private.current_tier()              to anon, authenticated;
grant execute on function private.has_feature(text)           to anon, authenticated;
grant execute on function private.caller_is_admin()           to anon, authenticated;
grant execute on function private.is_american_price(integer)  to anon, authenticated;
grant execute on function private.set_updated_at()            to anon, authenticated;
-- Public RPC: the caller's own tier.
grant execute on function public.my_tier()                    to anon, authenticated;
-- Admin RPC: callable by signed-in users, refuses anyone without the admin role.
grant execute on function public.admin_grant_membership(uuid, public.membership_tier, timestamptz, text) to authenticated;
grant execute on function public.admin_end_membership(uuid, text) to authenticated;
-- Deliberately NOT granted to clients:
--   public.effective_tier_for(uuid)  any user's tier, server only
--   private.effective_tier(uuid), private.is_admin(uuid)

do $$
declare
  t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- 2. Public reference data (Free, including signed-out visitors)
-- ---------------------------------------------------------------------------
grant select on
  public.tier_features,
  public.data_sources,
  public.venues,
  public.teams,
  public.players,
  public.games,
  public.game_results,
  public.team_game_stats,
  public.player_game_stats,
  public.sportsbooks,
  public.prop_markets,
  public.market_lines_current,
  public.injury_reports,
  public.model_versions,
  public.daily_insights
to anon, authenticated;

create policy "Anyone can read plan features"   on public.tier_features        for select to anon, authenticated using (true);
create policy "Anyone can read data sources"    on public.data_sources         for select to anon, authenticated using (true);
create policy "Anyone can read venues"          on public.venues               for select to anon, authenticated using (true);
create policy "Anyone can read teams"           on public.teams                for select to anon, authenticated using (true);
create policy "Anyone can read players"         on public.players              for select to anon, authenticated using (true);
create policy "Anyone can read game results"    on public.game_results         for select to anon, authenticated using (true);
create policy "Anyone can read team box scores" on public.team_game_stats      for select to anon, authenticated using (true);
create policy "Anyone can read player box scores" on public.player_game_stats  for select to anon, authenticated using (true);
create policy "Anyone can read sportsbooks"     on public.sportsbooks          for select to anon, authenticated using (true);
create policy "Anyone can read prop markets"    on public.prop_markets         for select to anon, authenticated using (true);

create policy "Schedules are on every plan" on public.games
  for select to anon, authenticated using (private.has_feature('games.schedule'));

create policy "Current lines are on every plan" on public.market_lines_current
  for select to anon, authenticated using (private.has_feature('games.schedule'));

create policy "Injury reports are on every plan" on public.injury_reports
  for select to anon, authenticated using (private.has_feature('injuries.basic'));

create policy "Only validated models are visible" on public.model_versions
  for select to anon, authenticated using (status in ('validated', 'retired'));

create policy "Published insights are on every plan" on public.daily_insights
  for select to anon, authenticated
  using (published_at is not null and private.has_feature('insights.daily'));

-- ---------------------------------------------------------------------------
-- 3. Plan-gated data
-- ---------------------------------------------------------------------------
grant select on
  public.odds_snapshots,
  public.player_prop_odds,
  public.team_ratings,
  public.team_rating_components,
  public.game_projections,
  public.game_projection_details,
  public.injury_impacts,
  public.player_projections,
  public.player_projection_distributions,
  public.prediction_results
to anon, authenticated;

create policy "Line movement: Plus" on public.odds_snapshots
  for select to anon, authenticated using (private.has_feature('games.lineMovement'));

create policy "Prop lines: Plus" on public.player_prop_odds
  for select to anon, authenticated using (private.has_feature('props.projections'));

create policy "Overall ratings: Free, published only" on public.team_ratings
  for select to anon, authenticated
  using (published_at is not null and private.has_feature('ratings.overall'));

create policy "Rating components: Pro" on public.team_rating_components
  for select to anon, authenticated
  using (
    private.has_feature('ratings.advanced')
    and exists (select 1 from public.team_ratings tr
                where tr.id = team_rating_id and tr.published_at is not null)
  );

create policy "Game projections: Free, published only" on public.game_projections
  for select to anon, authenticated
  using (published_at is not null and private.has_feature('games.basicProjections'));

create policy "Projected scores and matchups: Plus" on public.game_projection_details
  for select to anon, authenticated
  using (
    private.has_feature('games.projectedScores')
    and exists (select 1 from public.game_projections gp
                where gp.id = game_projection_id and gp.published_at is not null)
  );

create policy "Injury adjustments: Plus, published only" on public.injury_impacts
  for select to anon, authenticated
  using (published_at is not null and private.has_feature('injuries.adjustments'));

create policy "Player props: Plus, published only" on public.player_projections
  for select to anon, authenticated
  using (published_at is not null and private.has_feature('props.projections'));

create policy "Prop distributions: Pro" on public.player_projection_distributions
  for select to anon, authenticated
  using (
    private.has_feature('props.advanced')
    and exists (select 1 from public.player_projections pp
                where pp.id = player_projection_id and pp.published_at is not null)
  );

create policy "Graded history: Pro, published projections only" on public.prediction_results
  for select to anon, authenticated
  using (
    private.has_feature('history')
    and (
      exists (select 1 from public.game_projections gp
              where gp.id = game_projection_id and gp.published_at is not null)
      or exists (select 1 from public.player_projections pp
                 where pp.id = player_projection_id and pp.published_at is not null)
    )
  );

-- Views run with the caller's permissions (security_invoker = true).
grant select on public.current_injuries, public.model_performance to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 4. Accounts. Read your own rows; write nothing except your display fields.
-- ---------------------------------------------------------------------------
grant select on public.profiles, public.user_roles, public.customer_identities,
                public.memberships, public.membership_events
to authenticated;

-- Column-level grant: tier, role and identity live in other tables, and only
-- these two profile columns are user-editable at all.
grant update (display_name, timezone) on public.profiles to authenticated;

create policy "Read own profile" on public.profiles
  for select to authenticated using (id = auth.uid() or private.caller_is_admin());

create policy "Update own profile" on public.profiles
  for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

create policy "Read own roles" on public.user_roles
  for select to authenticated using (user_id = auth.uid());

create policy "Read own Shopify link" on public.customer_identities
  for select to authenticated using (user_id = auth.uid() or private.caller_is_admin());

create policy "Read own memberships" on public.memberships
  for select to authenticated using (user_id = auth.uid() or private.caller_is_admin());

create policy "Read own membership history" on public.membership_events
  for select to authenticated using (user_id = auth.uid() or private.caller_is_admin());

-- No insert/update/delete policies exist on memberships, user_roles,
-- customer_identities or membership_events, and no write privileges are
-- granted, so those writes fail for every client role.

-- shopify_webhook_events and external_ids: RLS on, no grants, no policies.
-- Service role only.

-- ---------------------------------------------------------------------------
-- 5. User-owned features
-- ---------------------------------------------------------------------------
grant select, insert, update, delete on public.watchlists, public.watchlist_items, public.alert_rules
to authenticated;

-- Watchlists (Plus). After a downgrade the user can still see and delete
-- their lists, but cannot create or change them.
create policy "Read own watchlists" on public.watchlists
  for select to authenticated using (user_id = auth.uid());
create policy "Delete own watchlists" on public.watchlists
  for delete to authenticated using (user_id = auth.uid());
create policy "Create watchlists: Plus" on public.watchlists
  for insert to authenticated
  with check (user_id = auth.uid() and private.has_feature('watchlists'));
create policy "Edit watchlists: Plus" on public.watchlists
  for update to authenticated
  using (user_id = auth.uid() and private.has_feature('watchlists'))
  with check (user_id = auth.uid());

create policy "Read own watchlist items" on public.watchlist_items
  for select to authenticated
  using (exists (select 1 from public.watchlists w where w.id = watchlist_id and w.user_id = auth.uid()));
create policy "Delete own watchlist items" on public.watchlist_items
  for delete to authenticated
  using (exists (select 1 from public.watchlists w where w.id = watchlist_id and w.user_id = auth.uid()));
create policy "Add watchlist items: Plus" on public.watchlist_items
  for insert to authenticated
  with check (
    private.has_feature('watchlists')
    and exists (select 1 from public.watchlists w where w.id = watchlist_id and w.user_id = auth.uid())
  );

-- Alert rules (Pro)
create policy "Read own alerts" on public.alert_rules
  for select to authenticated using (user_id = auth.uid());
create policy "Delete own alerts" on public.alert_rules
  for delete to authenticated using (user_id = auth.uid());
create policy "Create alerts: Pro" on public.alert_rules
  for insert to authenticated
  with check (user_id = auth.uid() and private.has_feature('alerts'));
create policy "Edit alerts: Pro" on public.alert_rules
  for update to authenticated
  using (user_id = auth.uid() and private.has_feature('alerts'))
  with check (user_id = auth.uid());
