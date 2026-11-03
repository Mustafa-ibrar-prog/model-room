-- Test-site plan switching for test accounts, without the service-role key.
--
-- The Account page's test controls (Switch to Plus / Pro, Downgrade to Free, Cancel, Expire now) call
-- public.test_simulate_membership() as the signed-in user. It is SECURITY DEFINER so it can write the
-- normal memberships table (users still have no write privileges or policies on it), and it refuses
-- unless ALL of these hold:
--   * this database has the flag private.app_settings('test_account_controls') = 'on'. Only the test
--     site's setup workflow sets it; a production database never has it, so the function is inert there;
--   * the caller is signed in, with a confirmed address ending in @modelroom.test;
--   * the change is one of: plus, pro, free, cancel, expire.
-- Every change goes through the existing memberships_audit trigger (membership_events), like any other.

create table private.app_settings (
  key   text primary key,
  value text not null
);
revoke all on table private.app_settings from public, anon, authenticated;
comment on table private.app_settings is 'Per-database switches. test_account_controls=on only on the test site''s database.';

create function public.test_simulate_membership(p_change text)
returns public.membership_tier
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  uid   uuid := auth.uid();
  addr  text;
  ok_at timestamptz;
  now_  timestamptz := now();
begin
  if coalesce((select value from private.app_settings where key = 'test_account_controls'), 'off') <> 'on' then
    raise exception 'Test account controls are off for this database.' using errcode = '42501';
  end if;
  if uid is null then
    raise exception 'Sign in first.' using errcode = '42501';
  end if;
  select lower(u.email), u.email_confirmed_at into addr, ok_at from auth.users u where u.id = uid;
  if addr is null or ok_at is null or right(addr, length('@modelroom.test')) <> '@modelroom.test' then
    raise exception 'Only confirmed test accounts can simulate subscriptions.' using errcode = '42501';
  end if;
  if p_change not in ('plus', 'pro', 'free', 'cancel', 'expire') then
    raise exception 'Unknown change: %', p_change using errcode = '22023';
  end if;

  if p_change = 'cancel' then
    -- Cancelled: access continues to the end of the paid period, then stops.
    update public.memberships
       set status = 'cancelled', current_period_end = now_ + interval '7 days'
     where user_id = uid and status in ('active', 'trialing', 'past_due');
  else
    update public.memberships
       set status = 'expired', ended_at = now_
     where user_id = uid and status in ('active', 'trialing', 'past_due', 'cancelled', 'paused');
    if p_change in ('plus', 'pro') then
      insert into public.memberships (user_id, tier, status, source, current_period_end, note)
      values (uid, p_change::public.membership_tier, 'active', 'admin', now_ + interval '30 days',
              'Test account: simulated subscription (no payment)');
    end if;
  end if;

  return private.effective_tier(uid);
end;
$$;

revoke all on function public.test_simulate_membership(text) from public, anon;
grant execute on function public.test_simulate_membership(text) to authenticated;
