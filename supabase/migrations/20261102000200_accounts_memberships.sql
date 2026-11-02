-- Model Room: accounts, identity links and memberships
--
-- Identity model (see docs/auth-architecture.md):
--   Shopify customer account  --(customer_identities)-->  profiles  --  auth.users
-- Shopify is the only login. Supabase stores the application profile,
-- roles and membership state. Users can read their own rows but can never
-- write memberships, roles or identity links.

-- ---------------------------------------------------------------------------
-- Profiles: one per Supabase auth user.
-- ---------------------------------------------------------------------------
create table public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  email         text,
  display_name  text check (char_length(display_name) between 1 and 80),
  timezone      text not null default 'America/Los_Angeles' check (char_length(timezone) <= 64),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table public.profiles is 'Model Room application profile. One row per auth.users row.';

create unique index profiles_email_lower_key on public.profiles (lower(email)) where email is not null;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function private.set_updated_at();

-- Create a profile automatically whenever the server creates an auth user.
create function private.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_auth_user();

-- ---------------------------------------------------------------------------
-- Roles: administrators. Writable only with the service role (SQL editor or
-- server code). There is deliberately no API path for granting roles.
-- ---------------------------------------------------------------------------
create table public.user_roles (
  user_id     uuid not null references public.profiles (id) on delete cascade,
  role        public.app_role not null,
  granted_by  uuid references public.profiles (id) on delete set null,
  note        text,
  created_at  timestamptz not null default now(),
  primary key (user_id, role)
);

-- ---------------------------------------------------------------------------
-- Customer identities: links a profile to a Shopify customer.
-- customer_gid is the Shopify Customer GID, shared by the Customer Account
-- API and the Admin API, so webhooks and logins resolve to the same profile.
-- ---------------------------------------------------------------------------
create table public.customer_identities (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.profiles (id) on delete cascade,
  provider       text not null default 'shopify' check (provider = 'shopify'),
  shop_id        text not null check (shop_id ~ '^[0-9]+$'),
  customer_gid   text not null check (customer_gid ~ '^gid://shopify/Customer/[0-9]+$'),
  email_at_link  text,
  linked_at      timestamptz not null default now(),
  last_login_at  timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (provider, shop_id, customer_gid),
  unique (user_id, provider, shop_id)
);
comment on table public.customer_identities is 'Shopify customer to Model Room profile link. Written only by the server after a verified Shopify login.';

create trigger customer_identities_set_updated_at
  before update on public.customer_identities
  for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- Memberships. Free is the absence of an active paid membership, so tier is
-- always plus or pro here. A user may hold several rows (for example a
-- Shopify subscription and an admin comp); the highest active tier wins.
-- ---------------------------------------------------------------------------
create table public.memberships (
  id                                 uuid primary key default gen_random_uuid(),
  user_id                            uuid not null references public.profiles (id) on delete cascade,
  tier                               public.membership_tier not null check (tier <> 'free'),
  status                             public.membership_status not null default 'active',
  source                             public.membership_source not null,
  shopify_subscription_contract_gid  text unique
    check (shopify_subscription_contract_gid ~ '^gid://shopify/SubscriptionContract/[0-9]+$'),
  shopify_selling_plan_gid           text
    check (shopify_selling_plan_gid ~ '^gid://shopify/SellingPlan/[0-9]+$'),
  current_period_end                 timestamptz,
  started_at                         timestamptz not null default now(),
  ended_at                           timestamptz,
  granted_by                         uuid references public.profiles (id) on delete set null,
  note                               text check (char_length(note) <= 500),
  created_at                         timestamptz not null default now(),
  updated_at                         timestamptz not null default now(),
  constraint memberships_shopify_has_contract
    check (source <> 'shopify' or shopify_subscription_contract_gid is not null),
  constraint memberships_admin_is_attributed
    check (source <> 'admin' or granted_by is not null or note is not null),
  constraint memberships_dates_ordered
    check (ended_at is null or ended_at >= started_at),
  -- A cancelled membership must say when access stops.
  constraint memberships_cancelled_has_end
    check (status <> 'cancelled' or current_period_end is not null or ended_at is not null)
);
comment on table public.memberships is 'Paid access. Written only by the server (Shopify sync) or by administrators through admin_grant_membership().';

create index memberships_user_live_idx
  on public.memberships (user_id)
  where status in ('active', 'trialing', 'past_due', 'cancelled');

create trigger memberships_set_updated_at
  before update on public.memberships
  for each row execute function private.set_updated_at();

-- Audit trail for every membership change.
create table public.membership_events (
  id             bigint generated always as identity primary key,
  membership_id  uuid not null references public.memberships (id) on delete cascade,
  user_id        uuid not null references public.profiles (id) on delete cascade,
  action         text not null check (action in ('created', 'updated')),
  old_tier       public.membership_tier,
  new_tier       public.membership_tier not null,
  old_status     public.membership_status,
  new_status     public.membership_status not null,
  source         public.membership_source not null,
  actor_id       uuid,           -- auth.uid() of the admin, null for server/webhook writes
  created_at     timestamptz not null default now()
);
create index membership_events_user_idx on public.membership_events (user_id, created_at desc);

create function private.log_membership_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE'
     and new.tier is not distinct from old.tier
     and new.status is not distinct from old.status then
    return new;
  end if;

  insert into public.membership_events
    (membership_id, user_id, action, old_tier, new_tier, old_status, new_status, source, actor_id)
  values (
    new.id, new.user_id,
    case tg_op when 'INSERT' then 'created' else 'updated' end,
    case tg_op when 'UPDATE' then old.tier end, new.tier,
    case tg_op when 'UPDATE' then old.status end, new.status,
    new.source, auth.uid()
  );
  return new;
end;
$$;

create trigger memberships_audit
  after insert or update on public.memberships
  for each row execute function private.log_membership_change();

-- ---------------------------------------------------------------------------
-- Shopify webhook / Flow request log. Gives idempotency (each delivery is
-- processed once) and a record for debugging. Server only.
-- ---------------------------------------------------------------------------
create table public.shopify_webhook_events (
  id             bigint generated always as identity primary key,
  delivery_id    text not null unique,   -- X-Shopify-Webhook-Id, or the Flow run id
  topic          text not null,
  shop_domain    text,
  payload        jsonb not null,
  received_at    timestamptz not null default now(),
  processed_at   timestamptz,
  error          text
);
create index shopify_webhook_events_unprocessed_idx
  on public.shopify_webhook_events (received_at) where processed_at is null;

-- ---------------------------------------------------------------------------
-- Tier features: the database copy of MIN_TIER in src/lib/entitlements.ts.
-- RLS policies call private.has_feature('<feature>') so the database and the
-- app enforce the same rules. scripts/check-entitlements-sync.mjs fails if
-- the two drift apart.
-- ---------------------------------------------------------------------------
create table public.tier_features (
  feature      text primary key check (feature ~ '^[a-z][A-Za-z]*(\.[a-z][A-Za-z]*)*$'),
  min_tier     public.membership_tier not null,
  description  text,
  updated_at   timestamptz not null default now()
);

insert into public.tier_features (feature, min_tier, description) values
  ('games.schedule',           'free', 'NFL and NBA game schedules'),
  ('games.basicProjections',   'free', 'Model spread and total for each game'),
  ('games.edgeFinder.limited', 'free', 'Edges on the first games of the slate'),
  ('games.edgeFinder.full',    'plus', 'Edges on every game'),
  ('games.projectedScores',    'plus', 'Projected team scores'),
  ('games.lineMovement',       'plus', 'Opening line and market history'),
  ('games.matchupBreakdowns',  'plus', 'Matchup notes'),
  ('injuries.basic',           'free', 'Injury status reports'),
  ('injuries.adjustments',     'plus', 'Projected line impact of injuries'),
  ('props.projections',        'plus', 'Player prop projections and prop lines'),
  ('props.advanced',           'pro',  'Prop distributions and over share'),
  ('ratings.overall',          'free', 'Overall team power ratings'),
  ('ratings.advanced',         'pro',  'Offense, defense, pace and schedule ratings'),
  ('insights.daily',           'free', 'Daily insights'),
  ('watchlists',               'plus', 'Watchlists'),
  ('history',                  'pro',  'Historical model data and graded results'),
  ('alerts',                   'pro',  'Customizable alerts'),
  ('reports.download',         'pro',  'Downloadable reports');

-- ---------------------------------------------------------------------------
-- Security helpers
-- ---------------------------------------------------------------------------

-- Effective tier for any user. Grace: past_due keeps access, and access runs
-- three days past current_period_end to cover renewal timing.
create function private.effective_tier(p_user uuid)
returns public.membership_tier
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(max(m.tier), 'free'::public.membership_tier)
  from public.memberships m
  where p_user is not null
    and m.user_id = p_user
    and m.status in ('active', 'trialing', 'past_due', 'cancelled')
    and m.started_at <= now()
    and (m.current_period_end is null or m.current_period_end + interval '3 days' > now())
    and (m.ended_at is null or m.ended_at > now());
$$;

-- Tier of the current caller (anon resolves to free).
create function private.current_tier()
returns public.membership_tier
language sql
stable
security definer
set search_path = ''
as $$
  select private.effective_tier(auth.uid());
$$;

-- Does the current caller's plan include a feature? Unknown features are denied.
create function private.has_feature(p_feature text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(
    (select private.current_tier() >= tf.min_tier
       from public.tier_features tf
      where tf.feature = p_feature),
    false
  );
$$;

create function private.is_admin(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.user_roles r
    where r.user_id = p_user and r.role = 'admin'
  );
$$;

create function private.caller_is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select private.is_admin(auth.uid());
$$;

-- Caller-scoped helpers usable inside policies by any role.
grant execute on function private.current_tier()        to anon, authenticated, service_role;
grant execute on function private.has_feature(text)     to anon, authenticated, service_role;
grant execute on function private.caller_is_admin()     to anon, authenticated, service_role;
grant execute on function private.set_updated_at()      to anon, authenticated, service_role;
-- Arbitrary-user lookups: server only.
grant execute on function private.effective_tier(uuid)  to service_role;
grant execute on function private.is_admin(uuid)        to service_role;

-- ---------------------------------------------------------------------------
-- Public RPC functions
-- ---------------------------------------------------------------------------

-- The caller's own tier. Safe for any client.
create function public.my_tier()
returns public.membership_tier
language sql
stable
security definer
set search_path = ''
as $$
  select private.current_tier();
$$;
grant execute on function public.my_tier() to anon, authenticated, service_role;

-- Server lookup used by getViewer(). Service role only.
create function public.effective_tier_for(p_user uuid)
returns public.membership_tier
language sql
stable
security definer
set search_path = ''
as $$
  select private.effective_tier(p_user);
$$;
grant execute on function public.effective_tier_for(uuid) to service_role;

-- Manual membership grant. Administrators only.
create function public.admin_grant_membership(
  p_user        uuid,
  p_tier        public.membership_tier,
  p_period_end  timestamptz default null,
  p_note        text default null
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id uuid;
begin
  if not private.is_admin(auth.uid()) then
    raise exception 'Only administrators can assign memberships.' using errcode = '42501';
  end if;
  if p_tier = 'free' then
    raise exception 'Free is the default. Use admin_end_membership to remove paid access.' using errcode = '22023';
  end if;
  if p_period_end is not null and p_period_end <= now() then
    raise exception 'p_period_end must be in the future.' using errcode = '22023';
  end if;

  insert into public.memberships (user_id, tier, status, source, current_period_end, granted_by, note)
  values (p_user, p_tier, 'active', 'admin', p_period_end, auth.uid(), p_note)
  returning id into v_id;

  return v_id;
end;
$$;
grant execute on function public.admin_grant_membership(uuid, public.membership_tier, timestamptz, text) to authenticated;

-- End an admin-granted membership. Shopify memberships follow Shopify and
-- cannot be ended here, so the two systems never disagree.
create function public.admin_end_membership(p_membership uuid, p_note text default null)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not private.is_admin(auth.uid()) then
    raise exception 'Only administrators can change memberships.' using errcode = '42501';
  end if;

  update public.memberships
     set status = 'expired',
         ended_at = now(),
         note = coalesce(p_note, note)
   where id = p_membership
     and source = 'admin';

  if not found then
    raise exception 'No admin-granted membership with that id.' using errcode = 'P0002';
  end if;
end;
$$;
grant execute on function public.admin_end_membership(uuid, text) to authenticated;
