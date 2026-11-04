-- Reliable refresh trigger for the TEST SITE: pg_cron dispatches the "Preview" GitHub Actions workflow every
-- 5 minutes with mode=plan. The workflow's planner (modeling/modelroom/refresh_plan.py) decides whether a slot
-- is due (7:00 AM / 12:00 PM / 4:00 PM PT, NFL kickoff − 90 min, every game − 30 min), logs every run, retries
-- failed slots, and never runs a slot twice. GitHub's own schedule stays on as a backup trigger.
--
-- The GitHub token lives ONLY in Supabase Vault (secret name: model_room_github_dispatch), never in a table,
-- a migration or the frontend. It should be a fine-grained token limited to this one repository with
-- "Actions: Read and write" (nothing else). Store it from the Supabase SQL editor:
--     select vault.create_secret('<token>', 'model_room_github_dispatch', 'Model Room: dispatch the Preview workflow');
-- Rotate:  select vault.update_secret((select id from vault.secrets where name = 'model_room_github_dispatch'), '<new token>');
--
-- Inert unless private.app_settings('refresh_scheduler') = 'on'. Only the test site's setup workflow sets it,
-- so a production database never dispatches anything.

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

create schema if not exists scheduler;
revoke all on schema scheduler from public, anon, authenticated;

-- One row per dispatch attempt (no secrets): failure detection = a non-204 status, a pg_net error, or no token.
create table scheduler.dispatch_log (
  id            bigserial primary key,
  requested_at  timestamptz not null default now(),
  request_id    bigint,
  status_code   integer,
  response      text,
  error         text,
  checked_at    timestamptz
);
revoke all on table scheduler.dispatch_log from public, anon, authenticated;
alter table scheduler.dispatch_log enable row level security;  -- no policies: invisible to API roles
comment on table scheduler.dispatch_log is 'Model Room refresh dispatches to GitHub Actions (204 = accepted). No secrets.';

create or replace function scheduler.dispatch_refresh()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  tok text;
  rid bigint;
begin
  if coalesce((select value from private.app_settings where key = 'refresh_scheduler'), 'off') <> 'on' then
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
exception when others then
  insert into scheduler.dispatch_log (error) values (left(sqlerrm, 300));
end;
$$;

-- Copies pg_net's response status onto the log (GitHub answers 204 when it accepted the dispatch) and keeps
-- 30 days of history.
create or replace function scheduler.check_dispatches()
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  update scheduler.dispatch_log l
     set status_code = r.status_code,
         response = left(coalesce(r.content::text, r.error_msg), 300),
         checked_at = now()
    from net._http_response r
   where r.id = l.request_id and l.status_code is null;
  delete from scheduler.dispatch_log where requested_at < now() - interval '30 days';
end;
$$;

revoke all on function scheduler.dispatch_refresh() from public, anon, authenticated;
revoke all on function scheduler.check_dispatches() from public, anon, authenticated;

-- Health at a glance (SQL editor): last dispatch, last accepted one, failures in the last 24 hours.
create or replace view scheduler.health as
select
  (select max(requested_at) from scheduler.dispatch_log) as last_dispatch,
  (select max(requested_at) from scheduler.dispatch_log where status_code = 204) as last_accepted,
  (select count(*) from scheduler.dispatch_log
    where requested_at > now() - interval '24 hours' and (error is not null or (status_code is not null and status_code <> 204))) as failures_24h,
  (select coalesce(value, 'off') from private.app_settings where key = 'refresh_scheduler') as enabled;
revoke all on scheduler.health from public, anon, authenticated;

select cron.schedule('model-room-refresh-dispatch', '*/5 * * * *', $$select scheduler.dispatch_refresh()$$);
select cron.schedule('model-room-refresh-check', '2-59/5 * * * *', $$select scheduler.check_dispatches()$$);
