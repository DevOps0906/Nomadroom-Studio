-- task-002: 수집 워커·작업 큐·프로필별 실행·워커 생존 신호
-- 근거: docs/05_DATA_MODEL.md#테이블, docs/02_ARCHITECTURE.md#3-3(상태 전이·재시도 상한은 API가 강제)

-- 워커(정책 없음 = 일반 사용자 전부 거부) ---------------------------------
create table public.workers (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  name text not null,
  token_hash text not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);
comment on table public.workers is '수집 워커 등록·토큰 해시(일반 사용자 접근 없음, API만)';
alter table public.workers enable row level security;
create index workers_workspace_id_idx on public.workers (workspace_id);

-- 작업 큐 ------------------------------------------------------------------
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  kind text not null check (kind in ('collect', 'verify')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'retrying', 'stopped', 'failed', 'done')),
  profile_ids uuid[] not null default '{}',
  params jsonb not null default '{}',
  idempotency_key text not null,
  retry_count integer not null default 0 check (retry_count >= 0),
  stop_requested boolean not null default false,
  requested_by uuid references auth.users (id) on delete set null,
  claimed_by uuid references public.workers (id) on delete set null,
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  unique (workspace_id, idempotency_key)
);
comment on table public.jobs is '작업 큐(수집·검증 실행, 쓰기는 API만)';
alter table public.jobs enable row level security;
create index jobs_requested_by_idx on public.jobs (requested_by);
create index jobs_claimed_by_idx on public.jobs (claimed_by);
-- 같은 kind의 queued·running 작업은 워크스페이스당 1개
create unique index jobs_one_active_per_kind_idx on public.jobs (workspace_id, kind)
  where status in ('queued', 'running');

create policy jobs_select_member on public.jobs
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 작업 안의 프로필별 진행 --------------------------------------------------
create table public.job_profile_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  job_id uuid not null references public.jobs (id) on delete cascade,
  profile_id uuid not null references public.profiles (id) on delete cascade,
  position integer not null check (position >= 0),
  chrome_state text check (chrome_state in ('ready', 'resize_needed', 'login_needed', 'error')),
  detail text,
  collected_count integer not null default 0 check (collected_count >= 0),
  status text not null default 'pending' check (status in ('pending', 'running', 'done', 'failed')),
  updated_at timestamptz not null default now(),
  unique (job_id, profile_id)
);
comment on table public.job_profile_runs is '작업 안의 프로필별 진행·Chrome 준비 상태(detail에 쿠키·경로 금지)';
alter table public.job_profile_runs enable row level security;
create index job_profile_runs_workspace_id_idx on public.job_profile_runs (workspace_id);
create index job_profile_runs_profile_id_idx on public.job_profile_runs (profile_id);

create policy job_profile_runs_select_member on public.job_profile_runs
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 워커 생존 신호(워커당 1행) ----------------------------------------------
create table public.worker_heartbeats (
  worker_id uuid primary key references public.workers (id) on delete cascade,
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  last_seen_at timestamptz not null default now(),
  current_job_id uuid references public.jobs (id) on delete set null,
  chrome jsonb not null default '{}'
);
comment on table public.worker_heartbeats is '워커 생존·현재 작업(워커당 1행 upsert)';
alter table public.worker_heartbeats enable row level security;
create index worker_heartbeats_workspace_id_idx on public.worker_heartbeats (workspace_id);
create index worker_heartbeats_current_job_id_idx on public.worker_heartbeats (current_job_id);

create policy worker_heartbeats_select_member on public.worker_heartbeats
  for select to authenticated
  using (public.is_workspace_member(workspace_id));
