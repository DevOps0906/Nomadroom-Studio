-- task-002: 후보 영상·관측값(추가 전용)·프로필별 판정
-- 근거: docs/05_DATA_MODEL.md#테이블, docs/01_PRD.md#9(판정 규칙·reason 코드 정본)

-- 후보 영상(영상 단위 1행) -------------------------------------------------
create table public.candidates (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  video_id text not null,
  title text not null,
  thumbnail_url text,
  genre text,
  category text,
  format text check (format in ('short', 'long')),
  market text,
  channel_id text,
  channel_title text,
  license_cc boolean,
  is_broadcaster boolean not null default false,
  used boolean not null default false,
  used_at timestamptz,
  rep_status text check (rep_status in ('producible', 'pending', 'excluded')),
  rep_profile_id uuid references public.profiles (id) on delete set null,
  status_changed_at timestamptz,
  first_job_id uuid references public.jobs (id) on delete set null,
  created_at timestamptz not null default now(),
  unique (workspace_id, video_id)
);
comment on table public.candidates is '수집된 후보 영상(license_cc null = 미확인, 쓰기는 API만)';
alter table public.candidates enable row level security;
create index candidates_rep_profile_id_idx on public.candidates (rep_profile_id);
create index candidates_first_job_id_idx on public.candidates (first_job_id);

create policy candidates_select_member on public.candidates
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 관측값(추가 전용, 180일 초과분만 삭제) -----------------------------------
create table public.observations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  candidate_id uuid not null references public.candidates (id) on delete cascade,
  observed_at timestamptz not null,
  view_count bigint not null check (view_count >= 0),
  license_cc boolean,
  channel_id text,
  source text not null default 'youtube_api' check (source in ('youtube_api')),
  -- no action: on delete set null은 UPDATE를 일으켜 추가 전용 트리거와 충돌한다
  job_id uuid references public.jobs (id)
);
comment on table public.observations is '시점별 관측값(추가 전용, 수정 불가)';
alter table public.observations enable row level security;
create index observations_workspace_id_idx on public.observations (workspace_id);
create index observations_candidate_observed_idx on public.observations (candidate_id, observed_at desc);
create index observations_job_id_idx on public.observations (job_id);

create policy observations_select_member on public.observations
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

create function public.observations_block_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'observations는 추가 전용입니다(수정 불가)'
    using errcode = 'restrict_violation';
end;
$$;
comment on function public.observations_block_update() is 'observations UPDATE 차단(service_role 포함)';
revoke execute on function public.observations_block_update() from public, anon, authenticated;

create trigger observations_append_only
  before update on public.observations
  for each row execute function public.observations_block_update();

-- 프로필별 판정 ------------------------------------------------------------
create table public.candidate_verdicts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  candidate_id uuid not null references public.candidates (id) on delete cascade,
  profile_id uuid not null references public.profiles (id) on delete cascade,
  status text not null check (status in ('producible', 'pending', 'excluded')),
  reason text check (reason in (
    'market', 'category', 'format', 'views_min', 'not_cc', 'broadcaster', 'keyword',
    'no_prev', 'license_unknown', 'growth_out_of_range'
  )),
  growth_pct numeric,
  prev_observation_id uuid references public.observations (id) on delete set null,
  curr_observation_id uuid references public.observations (id) on delete set null,
  judged_at timestamptz not null default now(),
  unique (candidate_id, profile_id)
);
comment on table public.candidate_verdicts is '프로필별 판정과 근거(최신 1행, reason 코드는 01_PRD.md#9)';
alter table public.candidate_verdicts enable row level security;
create index candidate_verdicts_workspace_id_idx on public.candidate_verdicts (workspace_id);
create index candidate_verdicts_profile_id_idx on public.candidate_verdicts (profile_id);
create index candidate_verdicts_prev_observation_id_idx on public.candidate_verdicts (prev_observation_id);
create index candidate_verdicts_curr_observation_id_idx on public.candidate_verdicts (curr_observation_id);

create policy candidate_verdicts_select_member on public.candidate_verdicts
  for select to authenticated
  using (public.is_workspace_member(workspace_id));
