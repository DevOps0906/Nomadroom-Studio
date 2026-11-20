-- task-054: AI 영상 생성(A-22, 기본 꺼짐) — 예산 칼럼·검수 칼럼·generation_runs·RPC
-- 근거: tasks/task-054.md#착수-결정 G0~G9, docs/04_API.md#A-22, docs/05_DATA_MODEL.md(generation_runs)
-- 상태: quoted → confirmed(제출 전 계상) → running(request_id) → finalizing(완료 처리 1건, CAS)
--   → done | failed | unknown. 계상(billable) = 확인 이후 전부, 플랫폼의 명확한 거부·미제출만 비계상(G2·G3).
-- 오류 SQLSTATE: NR009 없음 → 404 · NR010 상태 → 409 · NR011 다른 작업의 멱등 키 → 409 ·
--   NR012 입력(사진·권리·검수 값) → 400 · NR019 예산 초과(detail=남은 금액) → 409 budget_exceeded ·
--   NR020 owner 아님(확인=과금) → 403.
-- 리뷰 반영: 작업 삭제 시 run 보존(job_id null, 월 집계 유지) · 확인 후 5분 넘게 제출 기록 없는 confirmed는
--   unknown으로 마감(계상 유지, 재제출 없음) · 완료 선점 토큰(finalize_token)을 finish 조건에 포함.

-- 1) 워크스페이스 예산(G3): 0이면 AI 생성 불가. 변경은 SQL만(설정 화면 없음, G7) -----------------
alter table public.workspaces
  add column gen_monthly_budget_krw integer not null default 0
    constraint workspaces_gen_monthly_budget_chk check (gen_monthly_budget_krw >= 0),
  add column gen_job_cap_krw integer not null default 0
    constraint workspaces_gen_job_cap_chk check (gen_job_cap_krw >= 0);
comment on column public.workspaces.gen_monthly_budget_krw is
  'AI 영상 생성 월 예산(정수 원, KST 월, 0=사용 불가). SQL로만 설정(task-054 G7)';
comment on column public.workspaces.gen_job_cap_krw is
  'AI 영상 생성 작업당 상한(정수 원, 0=사용 불가). SQL로만 설정(task-054 G7)';

-- 2) 검수(G4): rights jsonb가 아닌 별도 칼럼, service_role RPC로만 갱신 ---------------------------
alter table public.production_assets
  add column reviewed boolean not null default false,
  add column review_checks jsonb,
  add constraint production_assets_review_checks_chk check (
    review_checks is null
    or (jsonb_typeof(review_checks) = 'object' and pg_column_size(review_checks) <= 1024));
comment on column public.production_assets.reviewed is
  'AI 생성 결과 사람 검수 완료(물리·앵글·사진 대조 3항목 모두 확인). review_generation_run만 갱신';
comment on column public.production_assets.review_checks is
  '검수 체크 {physics, angle, compare, reviewed_by, reviewed_at}';

-- 3) 생성 기록 ------------------------------------------------------------------------------
create table public.generation_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  job_id uuid,  -- 작업 삭제 시 null(비용·멱등 키 보존)
  source_asset_id uuid,
  result_asset_id uuid,
  cut_ref text check (cut_ref is null or char_length(cut_ref) between 1 and 50),
  prompt text not null check (char_length(prompt) between 1 and 500),
  platform text not null check (platform in ('xai')),
  model text not null check (char_length(model) between 1 and 100),
  duration_sec integer not null check (duration_sec between 1 and 15),
  est_cost_krw integer not null check (est_cost_krw >= 1),
  actual_cost_krw integer check (actual_cost_krw >= 0),
  billable boolean not null default false,
  status text not null default 'quoted' check (status in (
    'quoted', 'confirmed', 'running', 'finalizing', 'done', 'failed', 'unknown')),
  request_id text check (request_id is null or char_length(request_id) between 1 and 200),
  finalize_token uuid,
  error_code text check (error_code is null or error_code ~ '^[a-z0-9_]{1,40}$'),
  idempotency_key text not null check (char_length(idempotency_key) between 1 and 100),
  requested_by uuid references auth.users (id) on delete set null,
  confirmed_by uuid references auth.users (id) on delete set null,
  confirmed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint generation_runs_workspace_key_key unique (workspace_id, idempotency_key),
  constraint generation_runs_job_fk foreign key (job_id, workspace_id)
    references public.production_jobs (id, workspace_id) on delete set null (job_id),
  constraint generation_runs_source_fk foreign key (source_asset_id, job_id)
    references public.production_assets (id, job_id) on delete set null (source_asset_id),
  constraint generation_runs_result_fk foreign key (result_asset_id, job_id)
    references public.production_assets (id, job_id) on delete set null (result_asset_id),
  constraint generation_runs_request_chk
    check (status not in ('running', 'finalizing', 'done') or request_id is not null),
  constraint generation_runs_quoted_chk
    check ((status = 'quoted') = (confirmed_at is null) and (status <> 'quoted' or not billable))
);
comment on table public.generation_runs is
  'AI 영상 생성 요청 1회(A-22, task-054). 읽기: 구성원. 쓰기: API(service_role RPC)만. 키는 FastAPI만';
alter table public.generation_runs enable row level security;
create index generation_runs_job_id_idx on public.generation_runs (job_id);
create index generation_runs_workspace_confirmed_idx on public.generation_runs (workspace_id, confirmed_at);
create index generation_runs_source_asset_idx on public.generation_runs (source_asset_id);
create index generation_runs_result_asset_idx on public.generation_runs (result_asset_id);

create policy generation_runs_select_member on public.generation_runs
  for select to authenticated
  using (public.is_workspace_member(workspace_id));

revoke all on public.generation_runs from public, anon, authenticated;
grant select on public.generation_runs to authenticated;
grant select, insert, update, delete on public.generation_runs to service_role;

-- 4) 내부 헬퍼 -------------------------------------------------------------------------------
create function public._gen_run_json(p_run public.generation_runs)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select to_jsonb(p_run) - 'idempotency_key' - 'finalize_token';
$$;

-- 제출 전 중단 고착 마감: confirmed·request_id 없음·확인 후 5분 → unknown(계상 유지, 재제출 없음)
create function public._gen_expire_stalled(p_run uuid)
returns void
language sql
security definer
set search_path = ''
as $$
  update public.generation_runs r
    set status = 'unknown', error_code = 'submit_stalled', updated_at = now()
    where r.id = p_run and r.status = 'confirmed' and r.request_id is null
      and r.confirmed_at < now() - interval '5 minutes';
$$;

-- 남은 예산: 계상 run(billable)의 coalesce(actual, est) 합. 월 경계는 KST(G3)
create function public._gen_budget(p_workspace uuid, p_job uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'monthly_budget_krw', w.gen_monthly_budget_krw,
    'job_cap_krw', w.gen_job_cap_krw,
    'monthly_left_krw', w.gen_monthly_budget_krw - coalesce((
      select sum(coalesce(r.actual_cost_krw, r.est_cost_krw)) from public.generation_runs r
        where r.workspace_id = p_workspace and r.billable
          and r.confirmed_at >= (date_trunc('month', now() at time zone 'Asia/Seoul')
                                 at time zone 'Asia/Seoul')), 0),
    'job_left_krw', w.gen_job_cap_krw - coalesce((
      select sum(coalesce(r.actual_cost_krw, r.est_cost_krw)) from public.generation_runs r
        where r.workspace_id = p_workspace and r.job_id = p_job and r.billable), 0))
  from public.workspaces w where w.id = p_workspace;
$$;

-- 예산 확인: 0원 예산·상한이면 거부, 요청 est가 월·작업 남은 금액보다 크면 거부(detail=남은 금액)
create function public._gen_require_budget(p_workspace uuid, p_job uuid, p_est integer)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_budget jsonb := public._gen_budget(p_workspace, p_job);
  v_left bigint;
begin
  v_left := least((v_budget ->> 'monthly_left_krw')::bigint, (v_budget ->> 'job_left_krw')::bigint);
  if v_budget is null or (v_budget ->> 'monthly_budget_krw')::bigint <= 0
     or (v_budget ->> 'job_cap_krw')::bigint <= 0 or p_est > v_left then
    raise exception 'AI 생성 예산을 넘었습니다' using errcode = 'NR019',
      detail = greatest(coalesce(v_left, 0), 0)::text;
  end if;
  return v_budget;
end;
$$;

-- 입력 사진: 이 작업 소유 ready image, 권리 basis own·licensed, 인물이면 초상 동의(G0 권리 확인)
create function public._gen_check_source(p_workspace uuid, p_job uuid, p_asset uuid)
returns void
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_src public.production_assets%rowtype;
begin
  select * into v_src from public.production_assets a
    where a.id = p_asset and a.job_id = p_job and a.workspace_id = p_workspace;
  if not found or v_src.kind <> 'image' or v_src.status <> 'ready' then
    raise exception '입력 사진이 올바르지 않습니다' using errcode = 'NR012';
  end if;
  if coalesce(v_src.rights ->> 'basis', '') not in ('own', 'licensed')
     or (v_src.rights -> 'has_person' = 'true'::jsonb
         and v_src.rights -> 'portrait_consent' is distinct from 'true'::jsonb) then
    raise exception '입력 사진의 권리 기록이 필요합니다' using errcode = 'NR012';
  end if;
end;
$$;

-- 5) 견적(G1·G3): job 잠금 → 멱등 → 쇼핑·draft|failed(prepare) → 사진·권리 → 예산 → quoted ----------
create function public.quote_generation_run(
  p_workspace uuid, p_job uuid, p_user uuid, p_key text, p_source_asset uuid, p_prompt text,
  p_duration integer, p_cut_ref text, p_platform text, p_model text, p_est_cost integer
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_run public.generation_runs%rowtype;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select * into v_run from public.generation_runs r
    where r.workspace_id = p_workspace and r.idempotency_key = p_key;
  if found then
    if v_run.job_id is distinct from p_job then
      raise exception '다른 작업에 쓴 멱등 키입니다' using errcode = 'NR011';
    end if;
    return jsonb_build_object('replay', true, 'run', public._gen_run_json(v_run),
      'budget', public._gen_budget(p_workspace, p_job));
  end if;
  if v_job.kind <> 'shopping' then
    raise exception '쇼핑 작업만 AI 영상을 만들 수 있습니다.' using errcode = 'NR010';
  end if;
  if not (v_job.status = 'draft' or (v_job.status = 'failed' and v_job.failed_stage = 'prepare')) then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status) using errcode = 'NR010';
  end if;
  perform public._gen_check_source(p_workspace, p_job, p_source_asset);
  perform public._gen_require_budget(p_workspace, p_job, p_est_cost);
  insert into public.generation_runs
    (workspace_id, job_id, source_asset_id, cut_ref, prompt, platform, model, duration_sec,
     est_cost_krw, idempotency_key, requested_by)
  values (p_workspace, p_job, p_source_asset, p_cut_ref, p_prompt, p_platform, p_model, p_duration,
          p_est_cost, p_key, p_user)
  returning * into v_run;
  return jsonb_build_object('replay', false, 'run', public._gen_run_json(v_run),
    'budget', public._gen_budget(p_workspace, p_job));
end;
$$;

-- 6) 확인(G2·G3·G7): owner만 → workspace·job·run 잠금 → quoted 아니면 현재 run → 상태·사진·예산 재계산
--    → confirmed(billable). 같은 workspace의 확인은 workspace 행 잠금으로 직렬화된다.
create function public.confirm_generation_run(
  p_workspace uuid, p_job uuid, p_run uuid, p_user uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_run public.generation_runs%rowtype;
begin
  if not exists (select 1 from public.workspace_members m
                 where m.workspace_id = p_workspace and m.user_id = p_user and m.role = 'owner') then
    raise exception '확인은 워크스페이스 소유자만 할 수 있습니다' using errcode = 'NR020';
  end if;
  perform 1 from public.workspaces w where w.id = p_workspace for update;
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select * into v_run from public.generation_runs r
    where r.id = p_run and r.job_id = p_job and r.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '생성 요청이 없습니다' using errcode = 'NR009';
  end if;
  if v_run.status <> 'quoted' then
    perform public._gen_expire_stalled(p_run);
    select * into v_run from public.generation_runs r where r.id = p_run;
    return jsonb_build_object('replay', true, 'run', public._gen_run_json(v_run),
      'budget', public._gen_budget(p_workspace, p_job));
  end if;
  if not (v_job.status = 'draft' or (v_job.status = 'failed' and v_job.failed_stage = 'prepare')) then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status) using errcode = 'NR010';
  end if;
  perform public._gen_check_source(p_workspace, p_job, v_run.source_asset_id);
  perform public._gen_require_budget(p_workspace, p_job, v_run.est_cost_krw);
  update public.generation_runs r
    set status = 'confirmed', billable = true, confirmed_by = p_user, confirmed_at = now(),
        updated_at = now()
    where r.id = p_run
    returning * into v_run;
  return jsonb_build_object('replay', false, 'run', public._gen_run_json(v_run),
    'budget', public._gen_budget(p_workspace, p_job));
end;
$$;

-- 7) 제출 결과(G2): confirmed에서만. running(request_id) · unknown(계상 유지) ·
--    rejected(플랫폼의 명확한 거부 또는 미제출 → failed, 비계상)
create function public.mark_generation_submitted(
  p_workspace uuid, p_run uuid, p_outcome text, p_request_id text, p_error text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.generation_runs%rowtype;
begin
  select * into v_run from public.generation_runs r
    where r.id = p_run and r.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '생성 요청이 없습니다' using errcode = 'NR009';
  end if;
  if v_run.status <> 'confirmed' then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_run.status) using errcode = 'NR010';
  end if;
  if p_outcome = 'running' and p_request_id is not null then
    update public.generation_runs r
      set status = 'running', request_id = p_request_id, updated_at = now()
      where r.id = p_run returning * into v_run;
  elsif p_outcome = 'unknown' then
    update public.generation_runs r
      set status = 'unknown', error_code = p_error, updated_at = now()
      where r.id = p_run returning * into v_run;
  elsif p_outcome = 'rejected' then
    update public.generation_runs r
      set status = 'failed', billable = false, error_code = p_error, finished_at = now(),
          updated_at = now()
      where r.id = p_run returning * into v_run;
  else
    raise exception '제출 결과가 올바르지 않습니다' using errcode = 'NR012';
  end if;
  return public._gen_run_json(v_run);
end;
$$;

-- 8) 진행 확인(G5): 10분 넘게 멈춘 finalizing을 running으로 회수하고 현재 run을 돌려준다 -----------
create function public.begin_generation_refresh(p_workspace uuid, p_job uuid, p_run uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.generation_runs%rowtype;
begin
  update public.generation_runs r
    set status = 'running', finalize_token = null, updated_at = now()
    where r.id = p_run and r.job_id = p_job and r.workspace_id = p_workspace
      and r.status = 'finalizing' and r.updated_at < now() - interval '10 minutes';
  if exists (select 1 from public.generation_runs r
             where r.id = p_run and r.job_id = p_job and r.workspace_id = p_workspace) then
    perform public._gen_expire_stalled(p_run);
  end if;
  select * into v_run from public.generation_runs r
    where r.id = p_run and r.job_id = p_job and r.workspace_id = p_workspace;
  if not found then
    raise exception '생성 요청이 없습니다' using errcode = 'NR009';
  end if;
  return public._gen_run_json(v_run);
end;
$$;

-- 완료 처리 선점(CAS): running → finalizing 1건만, 새 토큰 발급. 선점 못 하면 null
create function public.claim_generation_finalize(p_workspace uuid, p_run uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.generation_runs%rowtype;
begin
  update public.generation_runs r
    set status = 'finalizing', finalize_token = gen_random_uuid(), updated_at = now()
    where r.id = p_run and r.workspace_id = p_workspace and r.status = 'running'
    returning * into v_run;
  if not found then
    return null;
  end if;
  return public._gen_run_json(v_run) || jsonb_build_object('finalize_token', v_run.finalize_token);
end;
$$;

-- 9) 완료(G1): finalizing에서만. done이면 결과를 source_upload(ready, basis ai_generated, 입력 사진 권리 승계
--    + gen)로 저장한다. 000023 트리거(상태·10건 상한)가 거부하면 failed(result_rejected), 비용은 계상 유지.
create function public.finish_generation_run(
  p_workspace uuid, p_run uuid, p_token uuid, p_status text, p_asset uuid, p_path text,
  p_size bigint, p_actual_cost integer, p_error text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.generation_runs%rowtype;
  v_rights jsonb;
begin
  select * into v_run from public.generation_runs r
    where r.id = p_run and r.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '생성 요청이 없습니다' using errcode = 'NR009';
  end if;
  -- 회수(10분) 뒤 다른 요청이 다시 선점했다면 이전 선점자는 덮어쓰지 못한다
  if v_run.status <> 'finalizing' or v_run.finalize_token is distinct from p_token then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_run.status) using errcode = 'NR010';
  end if;
  if p_actual_cost is not null and p_actual_cost < 0 then
    raise exception '비용이 올바르지 않습니다' using errcode = 'NR012';
  end if;
  if p_status = 'failed' then
    update public.generation_runs r
      set status = 'failed', error_code = p_error, actual_cost_krw = p_actual_cost,
          finalize_token = null, finished_at = now(), updated_at = now()
      where r.id = p_run returning * into v_run;
    return jsonb_build_object('run', public._gen_run_json(v_run), 'rejected', false);
  end if;
  if p_status <> 'done' or p_asset is null or p_path is null then
    raise exception '완료 값이 올바르지 않습니다' using errcode = 'NR012';
  end if;

  if v_run.job_id is null then  -- 작업이 삭제됨: 저장할 곳 없음(비용은 계상 유지)
    update public.generation_runs r
      set status = 'failed', error_code = 'result_rejected', actual_cost_krw = p_actual_cost,
          finalize_token = null, finished_at = now(), updated_at = now()
      where r.id = p_run returning * into v_run;
    return jsonb_build_object('run', public._gen_run_json(v_run), 'rejected', true);
  end if;
  select (coalesce(a.rights, '{}'::jsonb) - 'gen' - 'reviewed') into v_rights
    from public.production_assets a where a.id = v_run.source_asset_id and a.job_id = v_run.job_id;
  v_rights := coalesce(v_rights, '{}'::jsonb) || jsonb_build_object(
    'basis', 'ai_generated',
    'gen', jsonb_build_object('platform', v_run.platform, 'model', v_run.model,
      'request_id', v_run.request_id, 'cost_krw', coalesce(p_actual_cost, v_run.est_cost_krw)));
  begin
    insert into public.production_assets
      (id, workspace_id, job_id, kind, storage_path, mime, size_bytes, status, rights, created_by)
    values (p_asset, p_workspace, v_run.job_id, 'source_upload', p_path, 'video/mp4', p_size, 'ready',
            v_rights, v_run.confirmed_by);
  exception when sqlstate 'NR010' or unique_violation then
    update public.generation_runs r
      set status = 'failed', error_code = 'result_rejected', actual_cost_krw = p_actual_cost,
          finalize_token = null, finished_at = now(), updated_at = now()
      where r.id = p_run returning * into v_run;
    return jsonb_build_object('run', public._gen_run_json(v_run), 'rejected', true);
  end;
  update public.generation_runs r
    set status = 'done', result_asset_id = p_asset, actual_cost_krw = p_actual_cost,
        finalize_token = null, finished_at = now(), updated_at = now()
    where r.id = p_run returning * into v_run;
  return jsonb_build_object('run', public._gen_run_json(v_run), 'rejected', false);
end;
$$;

-- 10) 검수(G4): done 결과 자산에 3항목 기록, 셋 다 true일 때만 reviewed=true(요청자 본인 허용, G7) ------
create function public.review_generation_run(
  p_workspace uuid, p_job uuid, p_run uuid, p_user uuid, p_checks jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.generation_runs%rowtype;
  v_ok boolean;
  v_checks jsonb;
begin
  if jsonb_typeof(p_checks) is distinct from 'object'
     or jsonb_typeof(p_checks -> 'physics') is distinct from 'boolean'
     or jsonb_typeof(p_checks -> 'angle') is distinct from 'boolean'
     or jsonb_typeof(p_checks -> 'compare') is distinct from 'boolean' then
    raise exception '검수 항목이 올바르지 않습니다' using errcode = 'NR012';
  end if;
  select * into v_run from public.generation_runs r
    where r.id = p_run and r.job_id = p_job and r.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '생성 요청이 없습니다' using errcode = 'NR009';
  end if;
  if v_run.status <> 'done' or v_run.result_asset_id is null then
    raise exception '완료된 생성 결과만 검수할 수 있습니다.' using errcode = 'NR010';
  end if;
  v_ok := (p_checks ->> 'physics')::boolean and (p_checks ->> 'angle')::boolean
          and (p_checks ->> 'compare')::boolean;
  v_checks := jsonb_build_object('physics', p_checks -> 'physics', 'angle', p_checks -> 'angle',
    'compare', p_checks -> 'compare', 'reviewed_by', p_user, 'reviewed_at', now());
  update public.production_assets a
    set reviewed = v_ok, review_checks = v_checks
    where a.id = v_run.result_asset_id and a.job_id = p_job and a.workspace_id = p_workspace;
  return jsonb_build_object('run', public._gen_run_json(v_run), 'reviewed', v_ok,
    'review_checks', v_checks);
end;
$$;

-- 권한: 전부 API(service_role) 전용 ---------------------------------------------------------
revoke execute on function public._gen_run_json(public.generation_runs) from public, anon, authenticated;
revoke execute on function public._gen_expire_stalled(uuid) from public, anon, authenticated;
grant execute on function public._gen_expire_stalled(uuid) to service_role;
revoke execute on function public._gen_budget(uuid, uuid) from public, anon, authenticated;
revoke execute on function public._gen_require_budget(uuid, uuid, integer) from public, anon, authenticated;
revoke execute on function public._gen_check_source(uuid, uuid, uuid) from public, anon, authenticated;
revoke execute on function public.quote_generation_run(uuid, uuid, uuid, text, uuid, text, integer, text, text, text, integer)
  from public, anon, authenticated;
revoke execute on function public.confirm_generation_run(uuid, uuid, uuid, uuid) from public, anon, authenticated;
revoke execute on function public.mark_generation_submitted(uuid, uuid, text, text, text) from public, anon, authenticated;
revoke execute on function public.begin_generation_refresh(uuid, uuid, uuid) from public, anon, authenticated;
revoke execute on function public.claim_generation_finalize(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.finish_generation_run(uuid, uuid, uuid, text, uuid, text, bigint, integer, text)
  from public, anon, authenticated;
revoke execute on function public.review_generation_run(uuid, uuid, uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function public._gen_run_json(public.generation_runs) to service_role;
grant execute on function public._gen_budget(uuid, uuid) to service_role;
grant execute on function public._gen_require_budget(uuid, uuid, integer) to service_role;
grant execute on function public._gen_check_source(uuid, uuid, uuid) to service_role;
grant execute on function public.quote_generation_run(uuid, uuid, uuid, text, uuid, text, integer, text, text, text, integer)
  to service_role;
grant execute on function public.confirm_generation_run(uuid, uuid, uuid, uuid) to service_role;
grant execute on function public.mark_generation_submitted(uuid, uuid, text, text, text) to service_role;
grant execute on function public.begin_generation_refresh(uuid, uuid, uuid) to service_role;
grant execute on function public.claim_generation_finalize(uuid, uuid) to service_role;
grant execute on function public.finish_generation_run(uuid, uuid, uuid, text, uuid, text, bigint, integer, text)
  to service_role;
grant execute on function public.review_generation_run(uuid, uuid, uuid, uuid, jsonb) to service_role;
comment on function public.confirm_generation_run(uuid, uuid, uuid, uuid) is
  'A-22 확인(owner만·workspace/job/run 잠금·예산 재계산·confirmed 계상, 재확인은 현재 run). API 전용';
