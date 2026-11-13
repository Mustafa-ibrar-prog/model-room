-- Wake the Preview workflow only when a refresh slot is actually due (TEST SITE).
--
-- Before: pg_cron dispatched a GitHub Actions run every 5 minutes just to ask "is a slot due?". Almost every run
-- answered no and stopped, after a billable minute: about 288 runs a day for roughly 12 real refreshes.
-- Now: the question is answered here, in Postgres, where it is free. One row holds `next_check_at`, the time before
-- which nothing can be due; pg_cron still ticks every 5 minutes but only dispatches once that time has arrived.
--
-- `next_check_at` is written by the refresh run itself (scripts/scheduler-next.sh → refresh_plan.py next), so the
-- slot rules stay in one place: this file never computes a slot time. Safety nets, in order:
--   * the planner never asks to sleep more than 4 hours, so a game added after a run still gets its pre-game slot;
--   * if no run has reported for 6 hours, a dispatch goes out anyway rather than the scheduler going quiet;
--   * every dispatch takes a 15-minute lease, so a run that dies without reporting is retried, not hammered;
--   * after 12 dispatches with nothing reporting back, the lease stretches to 30 minutes and a note is logged for
--     the daily health check. It slows down; it never stops.
-- Nothing here changes what a refresh does, which slots exist, or the Odds API credit guards.

create table if not exists scheduler.plan (
  id                      boolean primary key default true check (id),
  next_check_at           timestamptz not null default now(),
  reason                  text,
  updated_at              timestamptz not null default now(),
  updated_by              text,
  dispatches_since_update integer not null default 0
);
revoke all on table scheduler.plan from public, anon, authenticated;
alter table scheduler.plan enable row level security;  -- no policies: invisible to the API roles
comment on table scheduler.plan is 'Model Room: when the refresh scheduler should next ask whether a slot is due. One row.';

-- Start due, so the first tick after this migration dispatches as usual.
insert into scheduler.plan (id, reason) values (true, 'created by migration') on conflict (id) do nothing;

-- Called by the refresh run once it knows when the next slot opens. Clamped so a bad value can neither put the
-- scheduler to sleep for a long time nor leave it dispatching in a loop.
create or replace function scheduler.set_next_check(at timestamptz, why text default null, by_run text default null)
returns timestamptz
language plpgsql
security definer
set search_path = ''
as $$
declare out_at timestamptz;
begin
  out_at := greatest(now(), least(at, now() + interval '6 hours'));
  insert into scheduler.plan (id, next_check_at, reason, updated_at, updated_by, dispatches_since_update)
       values (true, out_at, left(why, 300), now(), left(by_run, 100), 0)
  on conflict (id) do update
     set next_check_at = excluded.next_check_at, reason = excluded.reason,
         updated_at = now(), updated_by = excluded.updated_by, dispatches_since_update = 0;
  return out_at;
end;
$$;
revoke all on function scheduler.set_next_check(timestamptz, text, text) from public, anon, authenticated;

create or replace function scheduler.dispatch_refresh()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  tok text;
  rid bigint;
  p scheduler.plan%rowtype;
  lease interval;
begin
  if coalesce((select value from private.app_settings where key = 'refresh_scheduler'), 'off') <> 'on' then
    return;
  end if;
  select * into p from scheduler.plan where id;
  -- The saving: nothing can be due yet, so no workflow is started. A plan nobody has updated for 6 hours is
  -- treated as broken and dispatched anyway.
  if p.id is not null and now() < p.next_check_at and p.updated_at > now() - interval '6 hours' then
    return;
  end if;
  -- Duplicate protection at the trigger: never two dispatches within 4 minutes (pg_cron catching up, a manual call).
  if exists (select 1 from scheduler.dispatch_log where requested_at > now() - interval '4 minutes' and error is null) then
    return;
  end if;
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'model_room_github_dispatch' limit 1;
  if tok is null then
    if not exists (select 1 from scheduler.dispatch_log where error like 'no token%' and requested_at > now() - interval '1 hour') then
      insert into scheduler.dispatch_log (error) values ('no token in Vault (model_room_github_dispatch)');
    end if;
    return;
  end if;
  select net.http_post(
    url := 'https://api.github.com/repos/Mustafa-ibrar-prog/model-room/actions/workflows/preview.yml/dispatches',
    body := jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('mode', 'plan', 'trigger', 'supabase')),
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'model-room-scheduler',
                                  'Content-Type', 'application/json'),
    timeout_milliseconds := 15000
  ) into rid;
  insert into scheduler.dispatch_log (request_id) values (rid);
  -- Lease: hold the next check off while this run works. The run itself will set the real time when it finishes.
  lease := case when coalesce(p.dispatches_since_update, 0) >= 12 then interval '30 minutes' else interval '15 minutes' end;
  insert into scheduler.plan (id, next_check_at, reason, updated_at, dispatches_since_update)
       values (true, now() + lease, 'dispatched; waiting for the run to report', coalesce(p.updated_at, now()), 1)
  on conflict (id) do update
     set next_check_at = now() + lease,
         reason = 'dispatched; waiting for the run to report',
         dispatches_since_update = scheduler.plan.dispatches_since_update + 1;
  if coalesce(p.dispatches_since_update, 0) = 12
     and not exists (select 1 from scheduler.dispatch_log where error like 'no run has reported%' and requested_at > now() - interval '1 hour') then
    insert into scheduler.dispatch_log (error)
    values ('no run has reported back after 12 dispatches; checking every 30 minutes until one does');
  end if;
exception when others then
  insert into scheduler.dispatch_log (error) values (left(sqlerrm, 300));
end;
$$;
revoke all on function scheduler.dispatch_refresh() from public, anon, authenticated;

-- Health at a glance, now including the wake plan. Recreated, so the owner dashboard's read-only role is re-granted.
drop view if exists scheduler.health;
create view scheduler.health as
select
  (select max(requested_at) from scheduler.dispatch_log where request_id is not null) as last_dispatch,
  (select max(requested_at) from scheduler.dispatch_log where status_code = 204) as last_accepted,
  (select count(*) from scheduler.dispatch_log
    where requested_at > now() - interval '24 hours'
      and ((status_code is not null and status_code <> 204) or (error is not null and error not like 'no token%'))) as failures_24h,
  (select count(*) from scheduler.dispatch_log where requested_at > now() - interval '24 hours' and error like 'no token%') as no_token_notes_24h,
  (select count(*) from scheduler.dispatch_log where requested_at > now() - interval '24 hours' and request_id is not null and status_code is null) as awaiting_response,
  exists (select 1 from vault.secrets where name = 'model_room_github_dispatch') as token_stored,
  (select coalesce(value, 'off') from private.app_settings where key = 'refresh_scheduler') as enabled,
  (select next_check_at from scheduler.plan where id) as next_check_at,
  (select reason from scheduler.plan where id) as next_check_reason,
  (select updated_at from scheduler.plan where id) as plan_updated_at,
  (select updated_by from scheduler.plan where id) as plan_updated_by,
  (select dispatches_since_update from scheduler.plan where id) as dispatches_since_update,
  (select round(extract(epoch from (now() - next_check_at)) / 60) from scheduler.plan where id) as minutes_overdue,
  (select updated_at < now() - interval '6 hours' from scheduler.plan where id) as plan_stale;
revoke all on scheduler.health from public, anon, authenticated;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'owner_reader') then
    grant select on scheduler.health to owner_reader;
  end if;
end $$;
