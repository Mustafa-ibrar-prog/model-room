-- Scheduler health: "no token yet" is not a dispatch failure. failures_24h now counts only dispatches GitHub
-- rejected (non-204), pg_net errors and SQL errors; missing-token notes are counted separately, and the view
-- says whether the Vault secret exists (never its value). Test site only; nothing else changes.
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
  (select coalesce(value, 'off') from private.app_settings where key = 'refresh_scheduler') as enabled;
revoke all on scheduler.health from public, anon, authenticated;
