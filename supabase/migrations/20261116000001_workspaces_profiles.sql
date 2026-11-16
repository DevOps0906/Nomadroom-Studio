-- task-002: 워크스페이스·구성원·구성원 확인 헬퍼·프로필·방송사 목록
-- 근거: docs/05_DATA_MODEL.md#테이블. 브라우저는 읽기만(쓰기 정책 없음), 쓰기는 API(service_role)만.

-- 워크스페이스 ------------------------------------------------------------
create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);
comment on table public.workspaces is '워크스페이스(MVP 1개, 시드로 1행)';
alter table public.workspaces enable row level security;

-- 구성원 ------------------------------------------------------------------
create table public.workspace_members (
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);
comment on table public.workspace_members is '사용자-워크스페이스 소속(읽기는 본인 행만)';
alter table public.workspace_members enable row level security;
create index workspace_members_user_id_idx on public.workspace_members (user_id);

create policy workspace_members_select_own on public.workspace_members
  for select to authenticated
  using (user_id = (select auth.uid()));

-- 헬퍼: 현재 사용자가 워크스페이스 구성원인지 --------------------------------
create function public.is_workspace_member(ws uuid)
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select exists (
    select 1
    from public.workspace_members m
    where m.workspace_id = ws
      and m.user_id = (select auth.uid())
  );
$$;
comment on function public.is_workspace_member(uuid) is '현재 사용자(auth.uid())가 워크스페이스 구성원인지';
revoke execute on function public.is_workspace_member(uuid) from public, anon;
grant execute on function public.is_workspace_member(uuid) to authenticated;

create policy workspaces_select_member on public.workspaces
  for select to authenticated
  using (public.is_workspace_member(id));

-- 프로필 ------------------------------------------------------------------
create table public.profiles (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  name text not null,
  market text not null check (market in ('KR', 'JP')),
  format text not null default 'all' check (format in ('all', 'short', 'long')),
  category text,
  min_views integer not null default 0 check (min_views >= 0),
  max_growth_pct numeric not null check (max_growth_pct >= 0 and max_growth_pct <= 1000),
  keywords text[] not null default '{}' check (coalesce(array_length(keywords, 1), 0) <= 5),
  cc_only boolean not null default false,
  include_broadcast boolean not null default true,
  selected boolean not null default false,
  updated_at timestamptz not null default now()
);
comment on table public.profiles is '프로필별 수집 조건(쓰기는 API만, selected 최대 3은 API가 강제)';
alter table public.profiles enable row level security;
create index profiles_workspace_id_idx on public.profiles (workspace_id);

create policy profiles_select_member on public.profiles
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 방송사 목록 --------------------------------------------------------------
create table public.broadcaster_channels (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  channel_id text not null,
  channel_title text not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, channel_id)
);
comment on table public.broadcaster_channels is '방송사 채널 목록(목록에 있으면 방송사, 없으면 방송사 아님)';
alter table public.broadcaster_channels enable row level security;

create policy broadcaster_channels_select_member on public.broadcaster_channels
  for select to authenticated
  using (public.is_workspace_member(workspace_id));
