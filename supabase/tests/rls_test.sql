-- TEST ONLY. Security and integrity tests for the Model Room schema.
-- Run with: npm run db:test   (see scripts/db-test.sh)
--
-- Fixture rows below are throwaway test records in a scratch database.
-- Team names are deliberately fake and nothing here is sports data.

\set ON_ERROR_STOP on
\pset footer off
\pset tuples_only on

-- ---------------------------------------------------------------------------
-- Test helpers (security invoker, so they run as whatever role is active)
-- ---------------------------------------------------------------------------
create schema tests;
grant usage on schema tests to anon, authenticated, service_role;

create function tests.ok(cond boolean, label text) returns text language plpgsql as $$
begin
  if not coalesce(cond, false) then raise exception 'FAIL: %', label; end if;
  return 'ok    ' || label;
end $$;

create function tests.n(q text) returns bigint language plpgsql as $$
declare v bigint;
begin
  execute 'select count(*) from (' || q || ') s' into v;
  return v;
end $$;

-- Statement must fail with a privilege/RLS error, or affect zero rows.
create function tests.denied(stmt text, label text) returns text language plpgsql as $$
declare v bigint;
begin
  begin
    execute stmt;
    get diagnostics v = row_count;
  exception
    when insufficient_privilege then return 'ok    ' || label || '  [permission denied]';
    when others then
      if sqlstate = '42501' then return 'ok    ' || label || '  [rls]'; end if;
      raise exception 'FAIL: % (unexpected error % %)', label, sqlstate, sqlerrm;
  end;
  if v = 0 then return 'ok    ' || label || '  [0 rows]'; end if;
  raise exception 'FAIL: % (statement affected % rows)', label, v;
end $$;

-- Statement must raise the given SQLSTATE.
create function tests.raises(stmt text, code text, label text) returns text language plpgsql as $$
begin
  begin
    execute stmt;
  exception when others then
    if sqlstate = code then return 'ok    ' || label || '  [' || code || ']'; end if;
    raise exception 'FAIL: % (expected %, got % %)', label, code, sqlstate, sqlerrm;
  end;
  raise exception 'FAIL: % (no error raised)', label;
end $$;

grant execute on all functions in schema tests to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Fixtures (as the migration owner)
-- ---------------------------------------------------------------------------
\set free   '''a0000000-0000-4000-8000-000000000001'''
\set plus   '''a0000000-0000-4000-8000-000000000002'''
\set pro    '''a0000000-0000-4000-8000-000000000003'''
\set admin  '''a0000000-0000-4000-8000-000000000004'''
\set lapsed '''a0000000-0000-4000-8000-000000000005'''
\set cancel '''a0000000-0000-4000-8000-000000000006'''

insert into auth.users (id, email) values
  (:free, 'free@test.invalid'), (:plus, 'plus@test.invalid'), (:pro, 'pro@test.invalid'),
  (:admin, 'admin@test.invalid'), (:lapsed, 'lapsed@test.invalid'), (:cancel, 'cancel@test.invalid');

select tests.ok((select count(*) from public.profiles) = 6, 'profile is created for each new auth user');

insert into public.user_roles (user_id, role, note) values (:admin, 'admin', 'test fixture');

insert into public.customer_identities (user_id, shop_id, customer_gid, email_at_link)
values (:plus, '12345', 'gid://shopify/Customer/1001', 'plus@test.invalid');

insert into public.memberships (user_id, tier, status, source, shopify_subscription_contract_gid, current_period_end)
values (:plus, 'plus', 'active', 'shopify', 'gid://shopify/SubscriptionContract/5001', now() + interval '20 days');
insert into public.memberships (user_id, tier, status, source, shopify_subscription_contract_gid, current_period_end)
values (:pro, 'pro', 'active', 'shopify', 'gid://shopify/SubscriptionContract/5002', now() + interval '20 days');
insert into public.memberships (user_id, tier, status, source, shopify_subscription_contract_gid, current_period_end)
values (:lapsed, 'plus', 'active', 'shopify', 'gid://shopify/SubscriptionContract/5003', now() - interval '10 days');
insert into public.memberships (user_id, tier, status, source, shopify_subscription_contract_gid, current_period_end)
values (:cancel, 'pro', 'cancelled', 'shopify', 'gid://shopify/SubscriptionContract/5004', now() + interval '5 days');

insert into public.data_sources (key, name, kind) values ('test_feed', 'Test feed', 'multi');
insert into public.sportsbooks (key, name) values ('test_book', 'Test book');

insert into public.teams (id, league, abbreviation, location, nickname) values
  ('b0000000-0000-4000-8000-000000000001', 'nfl', 'TSA', 'Test', 'Alphas'),
  ('b0000000-0000-4000-8000-000000000002', 'nfl', 'TSB', 'Test', 'Betas'),
  ('b0000000-0000-4000-8000-000000000003', 'nba', 'TSC', 'Test', 'Gammas');

insert into public.players (id, league, full_name, current_team_id) values
  ('c0000000-0000-4000-8000-000000000001', 'nfl', 'Test Player', 'b0000000-0000-4000-8000-000000000001');

insert into public.games (id, league, season, week, starts_at, home_team_id, away_team_id, source_id)
values ('d0000000-0000-4000-8000-000000000001', 'nfl', 2030, 1, '2030-09-08 17:00+00',
        'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000002', 1);

insert into public.odds_snapshots (game_id, sportsbook_id, market, line, home_price, away_price, is_opening, captured_at, source_id)
values ('d0000000-0000-4000-8000-000000000001', 1, 'spread', -2.5, -110, -110, true,  '2030-09-01 12:00+00', 1),
       ('d0000000-0000-4000-8000-000000000001', 1, 'spread', -3.5, -110, -110, false, '2030-09-07 12:00+00', 1);

insert into public.model_versions (id, league, engine, version, status, validated_at) values
  ('e0000000-0000-4000-8000-000000000001', 'nfl', 'game', '1.0.0', 'validated', now()),
  ('e0000000-0000-4000-8000-000000000002', 'nfl', 'game', '1.1.0-dev', 'development', null),
  ('e0000000-0000-4000-8000-000000000003', 'nfl', 'player_props', '1.0.0', 'validated', now()),
  ('e0000000-0000-4000-8000-000000000004', 'nfl', 'team_ratings', '1.0.0', 'validated', now()),
  ('e0000000-0000-4000-8000-000000000005', 'nfl', 'injury_impact', '1.0.0', 'validated', now());

insert into public.game_projections (id, game_id, model_version_id, generated_at, model_spread_home, model_total, published_at) values
  ('f0000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001', now(), -6, 45, now()),
  ('f0000000-0000-4000-8000-000000000002', 'd0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000002', now(), -9, 50, null);
insert into public.game_projection_details (game_projection_id, projected_home_score, projected_away_score, matchup_note)
values ('f0000000-0000-4000-8000-000000000001', 25.5, 19.5, 'test note');

insert into public.player_projections (id, game_id, player_id, model_version_id, prop_market_key, projection, generated_at, published_at)
values ('f1000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000001',
        'e0000000-0000-4000-8000-000000000003', 'nfl.passing_yards', 250, now(), now());
insert into public.player_projection_distributions (player_projection_id, over_share, range_low, range_high)
values ('f1000000-0000-4000-8000-000000000001', 0.55, 200, 300);

insert into public.player_prop_odds (game_id, player_id, sportsbook_id, prop_market_key, line, over_price, under_price, captured_at, source_id)
values ('d0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000001', 1, 'nfl.passing_yards', 240.5, -110, -110, now(), 1);

insert into public.team_ratings (id, team_id, model_version_id, as_of, overall, published_at)
values ('f2000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000004', now(), 3.5, now());
insert into public.team_rating_components (team_rating_id, offense, defense) values ('f2000000-0000-4000-8000-000000000001', 2, 1.5);

insert into public.injury_reports (id, league, player_id, team_id, status, reported_at, source_id)
values ('f3000000-0000-4000-8000-000000000001', 'nfl', 'c0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000001', 'questionable', now(), 1);
insert into public.injury_impacts (injury_report_id, game_id, model_version_id, spread_impact, total_impact, generated_at, published_at)
values ('f3000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000005', 1.0, -0.5, now(), now());

insert into public.prediction_results (kind, game_projection_id, model_version_id, game_id, market_line, model_value, actual_value, edge, outcome)
values ('game_spread', 'f0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001',
        'd0000000-0000-4000-8000-000000000001', -3.5, -6, -7, 2.5, 'win');

\echo
\echo '== Data integrity'
select tests.ok((select line from public.market_lines_current) = -3.5, 'current line tracks the latest snapshot');
select tests.raises($$insert into public.game_projections (game_id, model_version_id, generated_at, model_spread_home, model_total, published_at)
  values ('d0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000002', now() + interval '1 s', -1, 40, now())$$,
  '23514', 'cannot publish projections from an unvalidated model');
select tests.raises($$update public.game_projections set published_at = now() where id = 'f0000000-0000-4000-8000-000000000002'$$,
  '23514', 'cannot publish an existing unvalidated projection later');
select tests.raises($$insert into public.games (league, season, starts_at, home_team_id, away_team_id, source_id)
  values ('nfl', 2030, now(), 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000003', 1)$$,
  '23503', 'game teams must belong to the game''s league');
select tests.raises($$insert into public.games (league, season, starts_at, home_team_id, away_team_id, source_id)
  values ('nfl', 2030, now(), 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000001', 1)$$,
  '23514', 'a team cannot play itself');
select tests.raises($$insert into public.odds_snapshots (game_id, sportsbook_id, market, line, over_price, under_price, captured_at, source_id)
  values ('d0000000-0000-4000-8000-000000000001', 1, 'moneyline', -3.5, -110, -110, now(), 1)$$,
  '23514', 'odds rows must match their market shape');
select tests.raises($$insert into public.odds_snapshots (game_id, sportsbook_id, market, line, home_price, away_price, captured_at, source_id)
  values ('d0000000-0000-4000-8000-000000000001', 1, 'spread', -3, -50, -110, now(), 1)$$,
  '23514', 'prices must be valid American odds');
select tests.raises($$insert into public.memberships (user_id, tier, source, shopify_subscription_contract_gid) values ('a0000000-0000-4000-8000-000000000001', 'free', 'shopify', 'gid://shopify/SubscriptionContract/9')$$,
  '23514', 'free is never stored as a membership row');
select tests.raises($$insert into public.memberships (user_id, tier, source) values ('a0000000-0000-4000-8000-000000000001', 'plus', 'shopify')$$,
  '23514', 'Shopify memberships need a subscription contract');
select tests.raises($$insert into public.customer_identities (user_id, shop_id, customer_gid) values ('a0000000-0000-4000-8000-000000000001', '12345', 'gid://shopify/Customer/1001')$$,
  '23505', 'a Shopify customer links to only one profile');
select tests.raises($$insert into public.games (league, season, starts_at, home_team_id, away_team_id) values ('nfl', 2030, now(), 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000002')$$,
  '23502', 'games must cite a data source');

-- ---------------------------------------------------------------------------
\echo
\echo '== Signed-out visitor (anon)'
set role anon;
select set_config('request.jwt.claims', '', false) as _claims \gset

select tests.ok(public.my_tier() = 'free', 'anon resolves to free');
select tests.ok(tests.n('select * from public.teams') = 3, 'can read teams');
select tests.ok(tests.n('select * from public.games') = 1, 'can read schedules');
select tests.ok(tests.n('select * from public.market_lines_current') = 1, 'can read current lines');
select tests.ok(tests.n('select * from public.game_projections') = 1, 'sees published basic projections only');
select tests.ok(tests.n('select * from public.injury_reports') = 1, 'can read basic injury reports');
select tests.ok(tests.n('select * from public.team_ratings') = 1, 'can read overall ratings');
select tests.ok(tests.n('select * from public.model_versions') = 4, 'sees validated model versions only');
select tests.ok(tests.n('select * from public.odds_snapshots') = 0, 'no line movement');
select tests.ok(tests.n('select * from public.game_projection_details') = 0, 'no projected scores');
select tests.ok(tests.n('select * from public.player_projections') = 0, 'no player prop projections');
select tests.ok(tests.n('select * from public.player_prop_odds') = 0, 'no player prop lines');
select tests.ok(tests.n('select * from public.player_projection_distributions') = 0, 'no prop distributions');
select tests.ok(tests.n('select * from public.injury_impacts') = 0, 'no injury adjustments');
select tests.ok(tests.n('select * from public.team_rating_components') = 0, 'no advanced ratings');
select tests.ok(tests.n('select * from public.prediction_results') = 0, 'no graded history');
select tests.denied('select * from public.memberships', 'cannot read memberships');
select tests.denied('select * from public.profiles', 'cannot read profiles');
select tests.denied('select * from public.shopify_webhook_events', 'cannot read webhook log');
select tests.denied('select * from public.external_ids', 'cannot read provider id map');
select tests.denied($$select public.effective_tier_for('a0000000-0000-4000-8000-000000000003')$$, 'cannot look up another user''s tier');
select tests.denied($$select public.admin_grant_membership('a0000000-0000-4000-8000-000000000001', 'pro')$$, 'cannot call admin grant');
select tests.denied($$insert into public.teams (league, abbreviation, location, nickname) values ('nfl', 'XXX', 'x', 'x')$$, 'cannot write sports data');
reset role;

-- ---------------------------------------------------------------------------
\echo
\echo '== Free member'
set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :free, 'role', 'authenticated')::text, false) as _claims \gset

select tests.ok(public.my_tier() = 'free', 'tier is free');
select tests.ok(tests.n('select * from public.player_projections') = 0, 'cannot retrieve player prop projections');
select tests.ok(tests.n('select * from public.player_prop_odds') = 0, 'cannot retrieve player prop lines');
select tests.ok(tests.n('select * from public.game_projection_details') = 0, 'cannot retrieve projected scores');
select tests.ok(tests.n('select * from public.odds_snapshots') = 0, 'cannot retrieve line movement');
select tests.ok(tests.n('select * from public.profiles') = 1, 'sees only own profile');
select tests.ok(tests.n('select * from public.memberships') = 0, 'cannot see other users'' memberships');
select tests.ok(tests.n('select * from public.customer_identities') = 0, 'cannot see other users'' Shopify links');
select tests.denied($$insert into public.memberships (user_id, tier, source, note) values ('a0000000-0000-4000-8000-000000000001', 'pro', 'admin', 'self-grant')$$, 'cannot grant self a membership');
select tests.denied($$insert into public.user_roles (user_id, role) values ('a0000000-0000-4000-8000-000000000001', 'admin')$$, 'cannot grant self admin');
select tests.denied($$update public.profiles set email = 'x@test.invalid' where id = 'a0000000-0000-4000-8000-000000000001'$$, 'cannot change own email column');
update public.profiles set display_name = 'Free tester' where id = :free;
select tests.ok((select display_name from public.profiles where id = :free) = 'Free tester', 'can edit own display name');
select tests.denied($$update public.profiles set display_name = 'hijack' where id = 'a0000000-0000-4000-8000-000000000002'$$, 'cannot edit another profile');
select tests.raises($$select public.admin_grant_membership('a0000000-0000-4000-8000-000000000001', 'pro')$$, '42501', 'non-admin cannot use admin grant');
select tests.denied($$insert into public.watchlists (user_id, name) values ('a0000000-0000-4000-8000-000000000001', 'Mine')$$, 'cannot create watchlists (Plus feature)');
select tests.denied($$insert into public.customer_identities (user_id, shop_id, customer_gid) values ('a0000000-0000-4000-8000-000000000001', '12345', 'gid://shopify/Customer/7')$$, 'cannot link a Shopify customer');
reset role;

-- ---------------------------------------------------------------------------
\echo
\echo '== Plus member'
set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :plus, 'role', 'authenticated')::text, false) as _claims \gset

select tests.ok(public.my_tier() = 'plus', 'tier is plus');
select tests.ok(tests.n('select * from public.player_projections') = 1, 'can read published prop projections');
select tests.ok(tests.n('select * from public.player_prop_odds') = 1, 'can read prop lines');
select tests.ok(tests.n('select * from public.game_projection_details') = 1, 'can read projected scores');
select tests.ok(tests.n('select * from public.odds_snapshots') = 2, 'can read line movement');
select tests.ok(tests.n('select * from public.injury_impacts') = 1, 'can read injury adjustments');
select tests.ok(tests.n('select * from public.game_projections') = 1, 'still cannot see unpublished projections');
select tests.ok(tests.n('select * from public.player_projection_distributions') = 0, 'no prop distributions (Pro)');
select tests.ok(tests.n('select * from public.team_rating_components') = 0, 'no advanced ratings (Pro)');
select tests.ok(tests.n('select * from public.prediction_results') = 0, 'no graded history (Pro)');
select tests.ok(tests.n('select * from public.memberships') = 1, 'sees own membership');
select tests.ok(tests.n('select * from public.customer_identities') = 1, 'sees own Shopify link');
select tests.denied($$update public.memberships set tier = 'pro' where user_id = 'a0000000-0000-4000-8000-000000000002'$$, 'cannot upgrade own membership');
select tests.denied($$update public.memberships set current_period_end = now() + interval '10 years'$$, 'cannot extend own membership');
select tests.denied($$delete from public.memberships$$, 'cannot delete memberships');
insert into public.watchlists (user_id, name) values (:plus, 'Sunday');
select tests.ok(tests.n('select * from public.watchlists') = 1, 'can create a watchlist');
select tests.denied($$insert into public.watchlists (user_id, name) values ('a0000000-0000-4000-8000-000000000001', 'planted')$$, 'cannot create a watchlist for someone else');
select tests.denied($$insert into public.alert_rules (user_id, kind) values ('a0000000-0000-4000-8000-000000000002', 'edge_threshold')$$, 'cannot create alerts (Pro feature)');
reset role;

-- ---------------------------------------------------------------------------
\echo
\echo '== Pro member'
set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :pro, 'role', 'authenticated')::text, false) as _claims \gset

select tests.ok(public.my_tier() = 'pro', 'tier is pro');
select tests.ok(tests.n('select * from public.player_projection_distributions') = 1, 'can read prop distributions');
select tests.ok(tests.n('select * from public.team_rating_components') = 1, 'can read advanced ratings');
select tests.ok(tests.n('select * from public.prediction_results') = 1, 'can read graded history');
select tests.ok(tests.n('select * from public.model_performance') = 1, 'can read model performance');
select tests.ok(tests.n('select * from public.watchlists') = 0, 'cannot see another member''s watchlists');
insert into public.alert_rules (user_id, kind, config) values (:pro, 'edge_threshold', '{"min_edge": 2}');
select tests.ok(tests.n('select * from public.alert_rules') = 1, 'can create an alert');
reset role;

-- ---------------------------------------------------------------------------
\echo
\echo '== Membership timing'
set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :lapsed, 'role', 'authenticated')::text, false) as _claims \gset
select tests.ok(public.my_tier() = 'free', 'lapsed membership falls back to free');
select tests.ok(tests.n('select * from public.player_projections') = 0, 'lapsed member loses prop access');
select set_config('request.jwt.claims', json_build_object('sub', :cancel, 'role', 'authenticated')::text, false) as _claims \gset
select tests.ok(public.my_tier() = 'pro', 'cancelled membership keeps access until period end');
reset role;

-- ---------------------------------------------------------------------------
\echo
\echo '== Administrator'
set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :admin, 'role', 'authenticated')::text, false) as _claims \gset

select tests.ok(tests.n('select * from public.memberships') = 4, 'admin can review all memberships');
select tests.ok(public.admin_grant_membership(:free, 'plus', now() + interval '30 days', 'test comp') is not null, 'admin can grant a membership');
select tests.raises($$select public.admin_grant_membership('a0000000-0000-4000-8000-000000000001', 'free')$$, '22023', 'admin cannot grant free');
select tests.raises($$select public.admin_end_membership((select id from public.memberships where source = 'shopify' limit 1))$$, 'P0002', 'admin cannot end a Shopify-managed membership');
select tests.denied($$update public.memberships set tier = 'pro'$$, 'admin cannot edit memberships directly');
select tests.denied($$insert into public.user_roles (user_id, role) values ('a0000000-0000-4000-8000-000000000002', 'admin')$$, 'admin cannot grant roles over the API');
reset role;

set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :free, 'role', 'authenticated')::text, false) as _claims \gset
select tests.ok(public.my_tier() = 'plus', 'granted user is now plus');
select tests.ok(tests.n('select * from public.player_projections') = 1, 'granted user can read props');
select tests.ok(tests.n('select * from public.membership_events') = 1, 'grant appears in the user''s history');
reset role;

set role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :admin, 'role', 'authenticated')::text, false) as _claims \gset
select public.admin_end_membership((select id from public.memberships where user_id = :free), 'test end') is null as ended \gset
reset role;
select tests.ok(public.effective_tier_for(:free) = 'free', 'ended grant returns the user to free');
select tests.ok((select count(*) from public.membership_events where user_id = :free) = 2, 'grant and end are both audited');
select tests.ok((select actor_id from public.membership_events where user_id = :free order by id limit 1) = :admin, 'audit records which admin acted');

-- ---------------------------------------------------------------------------
\echo
\echo '== Service role (server)'
set role service_role;
select tests.ok(tests.n('select * from public.player_projections') = 1, 'server can read all projections');
select tests.ok(tests.n('select * from public.game_projections') = 2, 'server sees unpublished projections for backtests');
select tests.ok(public.effective_tier_for(:pro) = 'pro', 'server can look up a user''s tier');
reset role;

\echo
\echo 'All database tests passed.'
