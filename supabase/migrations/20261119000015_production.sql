-- task-020: 제작 스키마(production_jobs·production_assets·edit_revisions·render_runs)·RLS·Storage 버킷
-- 근거: docs/05_DATA_MODEL.md#제작-테이블·#storage, docs/02b_PRODUCTION_FLOW.md#2, tasks/task-020.md#착수-결정(C1~C8)
-- 쓰기는 API(service_role)만. 브라우저(authenticated)는 같은 워크스페이스 조회만, anon은 없음.
-- 쇼핑·일본어판 칼럼(kind·vertical·brief·affiliates·rights·derived_from)·generation_runs·lang 'ja'는 task-042.

-- 제작 작업 ----------------------------------------------------------------
create table public.production_jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  title text not null,
  format text not null default 'category' check (format in ('category', 'variety')),
  status text not null default 'draft'
    check (status in ('draft', 'preparing', 'review', 'rendering', 'inspect', 'done', 'failed')),
  failed_stage text check (failed_stage in ('prepare', 'audio', 'render')),
  error_code text,
  transcribe_state text check (transcribe_state in ('queued', 'running', 'done', 'failed')),
  transcribe_error text check (transcribe_error in ('transcribe_failed', 'worker_offline')),
  transcribe_updated_at timestamptz,
  candidate_id uuid references public.candidates (id) on delete set null,
  source_kind text not null default 'upload' check (source_kind in ('upload', 'url')),
  source_url text check (source_url ~ '^https?://'),
  rights_confirmed boolean not null default false,
  rights_confirmed_by uuid references auth.users (id) on delete set null,
  rights_confirmed_at timestamptz,
  license_cc boolean,
  credit text,
  source_start_sec numeric not null default 0 check (source_start_sec >= 0),
  segment_len_sec numeric not null check (segment_len_sec > 0 and segment_len_sec <= 180),
  lang text not null default 'ko' check (lang in ('ko')),
  preset_version text not null,
  source_meta jsonb,
  current_revision_id uuid,
  ai_draft_count integer not null default 0 check (ai_draft_count >= 0),
  retry_count integer not null default 0 check (retry_count >= 0),
  claimed_by uuid references public.workers (id) on delete set null,
  updated_at timestamptz not null default now(),
  requested_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (id, workspace_id),
  constraint production_jobs_url_rights_chk
    check (source_kind <> 'url' or (source_url is not null and rights_confirmed))
);
comment on table public.production_jobs is '제작 작업 1건(원본·구간·상태, 쓰기는 API만, updated_at 트리거 없음)';
alter table public.production_jobs enable row level security;
create index production_jobs_ws_status_created_idx on public.production_jobs (workspace_id, status, created_at desc);
create index production_jobs_candidate_id_idx on public.production_jobs (candidate_id);
create index production_jobs_claimed_by_idx on public.production_jobs (claimed_by);

create policy production_jobs_select_member on public.production_jobs
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 편집안 리비전 ------------------------------------------------------------
create table public.edit_revisions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  job_id uuid not null,
  lang text not null default 'ko' check (lang in ('ko')),
  rev_no integer not null check (rev_no >= 1),
  schema_version integer not null default 1 check (schema_version >= 1),
  spec jsonb not null default '{}',
  origin text not null default 'user' check (origin in ('user', 'ai_draft')),
  validation jsonb not null default '{"errors": [], "warnings": []}',
  approved_at timestamptz,
  approved_by uuid references auth.users (id) on delete set null,
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (job_id, lang, rev_no),
  unique (id, job_id)
);
comment on table public.edit_revisions is '편집안 리비전(승인 고정 단위, 쓰기는 API만)';
alter table public.edit_revisions enable row level security;
create index edit_revisions_workspace_id_idx on public.edit_revisions (workspace_id);

create policy edit_revisions_select_member on public.edit_revisions
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 제작 자산(파일 메타, 내용은 Storage) --------------------------------------
create table public.production_assets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  job_id uuid not null,
  kind text not null check (kind in (
    'source_upload', 'source', 'analysis', 'sheet', 'hook_audio', 'narration',
    'output_mp4', 'report', 'transcript')),
  storage_path text not null unique,
  mime text not null,
  size_bytes bigint check (size_bytes >= 0),
  duration_sec numeric check (duration_sec >= 0),
  status text not null default 'pending' check (status in ('pending', 'ready')),
  render_run_id uuid,
  created_by uuid,
  created_at timestamptz not null default now(),
  unique (id, job_id),
  -- 경로 규칙 {workspace_id}/{job_id}/{asset_id}.{ext}(05 #storage, 서버가 생성)
  constraint production_assets_path_chk
    check (storage_path ~ ('^' || workspace_id::text || '/' || job_id::text || '/' || id::text || '\.[a-z0-9]{2,4}$')),
  constraint production_assets_render_run_kind_chk
    check (render_run_id is null or kind in ('output_mp4', 'report', 'hook_audio'))
);
comment on table public.production_assets is '제작 자산 파일 메타(내용은 비공개 버킷 production, 서명 URL은 API만, created_by=사용자 또는 워커 id)';
alter table public.production_assets enable row level security;
create index production_assets_workspace_id_idx on public.production_assets (workspace_id);
create index production_assets_job_kind_idx on public.production_assets (job_id, kind);
create index production_assets_render_run_id_idx on public.production_assets (render_run_id);

create policy production_assets_select_member on public.production_assets
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 렌더 실행 ----------------------------------------------------------------
create table public.render_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  job_id uuid not null,
  revision_id uuid not null,
  lang text not null default 'ko' check (lang in ('ko')),
  attempt integer not null default 1 check (attempt >= 1),
  retry_of uuid,
  idempotency_key text not null,
  preset_version text not null,
  status text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  progress_pct integer not null default 0 check (progress_pct between 0 and 100),
  progress_stage text,
  error_stage text check (error_stage in ('audio', 'render')),
  error_code text,
  claimed_by uuid references public.workers (id) on delete set null,
  mp4_asset_id uuid,
  report_asset_id uuid,
  hook_audio_asset_id uuid,
  requested_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key),
  unique (id, job_id)
);
comment on table public.render_runs is '렌더 실행 1회(멱등·재시도 단위, 쓰기는 API만, 완료 run 자산 불변)';
alter table public.render_runs enable row level security;
create index render_runs_job_id_idx on public.render_runs (job_id, created_at desc);
create index render_runs_revision_id_idx on public.render_runs (revision_id, job_id);
create index render_runs_claimed_by_idx on public.render_runs (claimed_by);
-- 워크스페이스당 진행 중 렌더 1건(동시 렌더 없음)
create unique index render_runs_active_ws_uidx on public.render_runs (workspace_id)
  where status in ('queued', 'running');
-- 같은 (작업, 리비전, 언어)는 진행·완료 1건(failed 제외 → 재시도는 새 행)
create unique index render_runs_active_rev_uidx on public.render_runs (job_id, revision_id, lang)
  where status in ('queued', 'running', 'done');

create policy render_runs_select_member on public.render_runs
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

-- 순환·소속 일관성 FK(C3·C4): 자식→job은 (job_id, workspace_id) cascade,
-- 리비전·자산·run 참조는 (id, job_id)로 같은 작업만, 삭제 시 참조 칼럼만 null
alter table public.edit_revisions
  add constraint edit_revisions_job_fk foreign key (job_id, workspace_id)
    references public.production_jobs (id, workspace_id) on delete cascade;
alter table public.production_assets
  add constraint production_assets_job_fk foreign key (job_id, workspace_id)
    references public.production_jobs (id, workspace_id) on delete cascade;
alter table public.render_runs
  add constraint render_runs_job_fk foreign key (job_id, workspace_id)
    references public.production_jobs (id, workspace_id) on delete cascade;

alter table public.production_jobs
  add constraint production_jobs_current_revision_fk foreign key (current_revision_id, id)
    references public.edit_revisions (id, job_id) on delete set null (current_revision_id);
alter table public.render_runs
  add constraint render_runs_revision_fk foreign key (revision_id, job_id)
    references public.edit_revisions (id, job_id);
alter table public.render_runs
  add constraint render_runs_retry_of_fk foreign key (retry_of, job_id)
    references public.render_runs (id, job_id) on delete set null (retry_of);
alter table public.render_runs
  add constraint render_runs_mp4_asset_fk foreign key (mp4_asset_id, job_id)
    references public.production_assets (id, job_id) on delete set null (mp4_asset_id);
alter table public.render_runs
  add constraint render_runs_report_asset_fk foreign key (report_asset_id, job_id)
    references public.production_assets (id, job_id) on delete set null (report_asset_id);
alter table public.render_runs
  add constraint render_runs_hook_audio_asset_fk foreign key (hook_audio_asset_id, job_id)
    references public.production_assets (id, job_id) on delete set null (hook_audio_asset_id);
alter table public.production_assets
  add constraint production_assets_render_run_fk foreign key (render_run_id, job_id)
    references public.render_runs (id, job_id) on delete set null (render_run_id);

create index production_jobs_current_revision_idx on public.production_jobs (current_revision_id);
create index render_runs_mp4_asset_idx on public.render_runs (mp4_asset_id);
create index render_runs_report_asset_idx on public.render_runs (report_asset_id);
create index render_runs_hook_audio_asset_idx on public.render_runs (hook_audio_asset_id);
create index render_runs_retry_of_idx on public.render_runs (retry_of);

-- 권한(C1): 000005가 기본 권한을 회수했으므로 명시 grant
revoke all on public.production_jobs, public.edit_revisions, public.production_assets, public.render_runs
  from public, anon, authenticated;
grant select on public.production_jobs, public.edit_revisions, public.production_assets, public.render_runs
  to authenticated;
grant select, insert, update, delete on public.production_jobs, public.edit_revisions,
  public.production_assets, public.render_runs to service_role;

-- Storage 비공개 버킷(C7·C8): storage.objects 정책 없음 = 브라우저 역할 거부, 서명 URL만
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'production', 'production', false, 524288000,
  array[
    'video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska',
    'audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp4', 'audio/x-m4a',
    'application/json', 'image/jpeg'
  ]
)
on conflict (id) do nothing;
