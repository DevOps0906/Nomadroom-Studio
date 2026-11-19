-- task-023: 렌더 요청·재시도(A-15·A-16)와 제작 워커 API(W-05·W-09)·오프라인 만료의 원자적 RPC
-- 근거: tasks/task-023.md#착수-결정 E1~E10, docs/04_API.md#A-15·#A-16·#W-05~#W-09, docs/02b_PRODUCTION_FLOW.md#2
-- 모두 security definer·service_role 전용. 잠금 순서는 job → run(000016 RPC와 같음).
-- 오류 SQLSTATE(000016을 잇는다): NR009 = 없음(타 워크스페이스 포함) → 404,
--   NR010 = 상태 불가 → 409(message에 현재 상태), NR011 = 멱등 키가 다른 작업 것 → 409,
--   NR012 = 입력 검증(미승인·현재 아님 리비전, 자산 목록) → 400, NR013 = 60초 내 새 키 → 429,
--   NR014 = 진행·완료 렌더 있음(부분 unique) → 409, NR015 = 재시도 상한 초과 → 409.

-- E3 오프라인 지연 평가 -----------------------------------------------------------
-- running run·수령된 preparing job: max(updated_at, 수령 시각)에서 3분(04 W-08 정본) 지나면 worker_offline.
-- queued run: 10분 동안 수령되지 않으면 failed(worker_offline) — 워크스페이스 렌더 영구 잠금 방지.
-- 만료된 task의 pending 산출물 행은 지우고 경로를 돌려준다(Storage 객체 삭제는 API, 리뷰 반영 4).
-- API가 A-09 GET·A-15·A-16·W-05·W-08 앞에서 호출한다(다른 RPC 안에서 부르면 경로를 잃는다).
create function public.expire_production_offline(p_workspace uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_runs uuid[];
  v_jobs uuid[];
  v_paths text[];
begin
  -- 잠금 순서 job → run: 대상 run의 job과 대상 preparing job을 id 순으로 먼저 잠근다
  perform 1 from public.production_jobs j
    where j.workspace_id = p_workspace
      and (
        (j.status = 'preparing' and j.claimed_by is not null
          and j.updated_at < now() - interval '3 minutes')
        or j.id in (
          select r.job_id from public.render_runs r
          where r.workspace_id = p_workspace
            and ((r.status = 'running'
                  and greatest(r.updated_at, r.started_at) < now() - interval '3 minutes')
              or (r.status = 'queued' and r.created_at < now() - interval '10 minutes')))
      )
    order by j.id
    for update;

  with expired as (
    update public.render_runs r
      set status = 'failed', error_stage = 'render', error_code = 'worker_offline',
          finished_at = now(), updated_at = now()
      where r.workspace_id = p_workspace
        and ((r.status = 'running'
              and greatest(r.updated_at, r.started_at) < now() - interval '3 minutes')
          or (r.status = 'queued' and r.created_at < now() - interval '10 minutes'))
      returning r.id, r.job_id, r.lang
  ), failed_jobs as (
    -- ko run만 job 상태를 바꾼다(ja는 render_runs로만 추적)
    update public.production_jobs j
      set status = 'failed', failed_stage = 'render', error_code = 'worker_offline',
          updated_at = now()
      from expired e
      where j.id = e.job_id and e.lang = 'ko' and j.status = 'rendering'
      returning j.id
  )
  select coalesce(array_agg(e.id), '{}') into v_runs from expired e;

  with expired as (
    update public.production_jobs j
      set status = 'failed', failed_stage = 'prepare', error_code = 'worker_offline',
          updated_at = now()
      where j.workspace_id = p_workspace and j.status = 'preparing' and j.claimed_by is not null
        and j.updated_at < now() - interval '3 minutes'
      returning j.id
  )
  select coalesce(array_agg(e.id), '{}') into v_jobs from expired e;

  with gone as (
    delete from public.production_assets a
      where a.workspace_id = p_workspace and a.status = 'pending'
        and ((a.render_run_id = any(v_runs))
          or (a.job_id = any(v_jobs) and a.render_run_id is null
              and a.kind in ('source', 'analysis', 'sheet')))
      returning a.storage_path
  )
  select coalesce(array_agg(g.storage_path), '{}') into v_paths from gone g;

  return jsonb_build_object(
    'expired', cardinality(v_runs) + cardinality(v_jobs), 'deleted_paths', to_jsonb(v_paths));
end;
$$;
comment on function public.expire_production_offline(uuid) is
  'E3 제작 오프라인 지연 평가(running·preparing 3분, queued 10분 → worker_offline, pending 산출물 정리). API 전용';

-- run 응답 모양(A-15·A-16 공용) ---------------------------------------------------
create function public._render_run_json(p_run public.render_runs, p_created boolean)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select jsonb_build_object(
    'id', p_run.id, 'job_id', p_run.job_id, 'revision_id', p_run.revision_id,
    'lang', p_run.lang, 'status', p_run.status, 'attempt', p_run.attempt,
    'retry_of', p_run.retry_of, 'preset_version', p_run.preset_version,
    'created', p_created);
$$;

-- A-15 렌더 요청 ------------------------------------------------------------------
create function public.request_render_run(
  p_workspace uuid, p_job uuid, p_user uuid, p_revision uuid, p_lang text, p_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_rev public.edit_revisions%rowtype;
  v_run public.render_runs%rowtype;
  v_constraint text;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;

  -- 같은 키 재요청은 상태와 무관하게 기존 run(E8: 다른 작업의 키면 409)
  select * into v_run from public.render_runs r
    where r.workspace_id = p_workspace and r.idempotency_key = p_key;
  if found then
    if v_run.job_id <> p_job then
      raise exception '다른 작업에 쓴 멱등 키입니다' using errcode = 'NR011';
    end if;
    return public._render_run_json(v_run, false);
  end if;

  if v_job.status <> 'review' then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
      using errcode = 'NR010';
  end if;
  select * into v_rev from public.edit_revisions r
    where r.id = p_revision and r.job_id = p_job;
  if not found or v_rev.approved_at is null or v_rev.lang <> p_lang
     or v_rev.id is distinct from v_job.current_revision_id then
    raise exception '현재 승인된 리비전이 아닙니다' using errcode = 'NR012';
  end if;
  -- 진행 중 렌더(워크스페이스 1건)·같은 (작업, 리비전, 언어) 진행·완료 run이 먼저 409.
  -- 경합은 아래 insert의 부분 unique가 막는다.
  if exists (select 1 from public.render_runs r
             where r.workspace_id = p_workspace and r.status in ('queued', 'running'))
     or exists (select 1 from public.render_runs r
                where r.job_id = p_job and r.revision_id = p_revision and r.lang = p_lang
                  and r.status in ('queued', 'running', 'done')) then
    raise exception '진행 중이거나 완료된 렌더가 있습니다' using errcode = 'NR014';
  end if;
  if exists (select 1 from public.render_runs r
             where r.workspace_id = p_workspace and r.created_at > now() - interval '60 seconds') then
    raise exception '렌더를 너무 자주 요청했습니다' using errcode = 'NR013';
  end if;

  begin
    insert into public.render_runs
      (workspace_id, job_id, revision_id, lang, attempt, idempotency_key, preset_version, requested_by)
    values (p_workspace, p_job, p_revision, p_lang, 1, p_key, v_job.preset_version, p_user)
    returning * into v_run;
  exception when unique_violation then
    get stacked diagnostics v_constraint = constraint_name;
    if v_constraint = 'render_runs_workspace_id_idempotency_key_key' then
      -- 다른 작업이 같은 키로 먼저 만든 경우(같은 작업은 job 잠금으로 위에서 걸린다)
      raise exception '다른 작업에 쓴 멱등 키입니다' using errcode = 'NR011';
    end if;
    raise exception '진행 중이거나 완료된 렌더가 있습니다' using errcode = 'NR014';
  end;

  update public.production_jobs j
    set status = 'rendering', failed_stage = null, error_code = null, updated_at = now()
    where j.id = p_job;
  return public._render_run_json(v_run, true);
end;
$$;
comment on function public.request_render_run(uuid, uuid, uuid, uuid, text, text) is
  'A-15 렌더 요청(멱등 키·승인 현재 리비전·review→rendering·부분 unique) 한 트랜잭션. API 전용';

-- A-16 재시도 ---------------------------------------------------------------------
-- E5: job failed(audio·render)·run failed·run 리비전 = 현재 리비전·(작업, 리비전, 언어) 최신 run만.
-- attempt = 체인 최댓값 + 1, 상한 3. hook_too_long·text_too_long run은 거부(A-15로 다시 요청).
create function public.retry_render_run(p_workspace uuid, p_job uuid, p_user uuid, p_run uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_old public.render_runs%rowtype;
  v_run public.render_runs%rowtype;
  v_latest uuid;
  v_attempt integer;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select * into v_old from public.render_runs r
    where r.id = p_run and r.job_id = p_job and r.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '렌더 실행이 없습니다' using errcode = 'NR009';
  end if;
  -- null이 조건을 우회하지 않게 coalesce(리뷰 반영 6)
  if v_old.status <> 'failed'
     or coalesce(v_old.error_code, '') in ('hook_too_long', 'text_too_long')
     or v_job.status <> 'failed' or coalesce(v_job.failed_stage, '') not in ('audio', 'render')
     or v_old.revision_id is distinct from v_job.current_revision_id then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
      using errcode = 'NR010';
  end if;
  select r.id into v_latest from public.render_runs r
    where r.job_id = p_job and r.revision_id = v_old.revision_id and r.lang = v_old.lang
    order by r.created_at desc, r.attempt desc
    limit 1;
  if v_latest <> p_run then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
      using errcode = 'NR010';
  end if;
  select max(r.attempt) + 1 into v_attempt from public.render_runs r
    where r.job_id = p_job and r.revision_id = v_old.revision_id and r.lang = v_old.lang;
  if v_attempt > 3 then
    raise exception '재시도 횟수를 넘었습니다' using errcode = 'NR015';
  end if;

  begin
    insert into public.render_runs
      (workspace_id, job_id, revision_id, lang, attempt, retry_of, idempotency_key,
       preset_version, requested_by)
    values (p_workspace, p_job, v_old.revision_id, v_old.lang, v_attempt, p_run,
            'retry:' || p_run::text, v_old.preset_version, p_user)
    returning * into v_run;
  exception when unique_violation then
    raise exception '진행 중이거나 완료된 렌더가 있습니다' using errcode = 'NR014';
  end;

  update public.production_jobs j
    set status = 'rendering', failed_stage = null, error_code = null, updated_at = now()
    where j.id = p_job;
  return public._render_run_json(v_run, true);
end;
$$;
comment on function public.retry_render_run(uuid, uuid, uuid, uuid) is
  'A-16 렌더 재시도(새 run·attempt+1·같은 승인본·failed→rendering) 한 트랜잭션. API 전용';

-- W-05 수령 -----------------------------------------------------------------------
-- E2: 자기 running run·자기 preparing job이 있으면 그것(재시작 복구), 없으면 가장 오래된
-- 대기 task 1건을 skip locked로 잠가 조건부 갱신. 없으면 null.
create function public.claim_production_task(p_workspace uuid, p_worker uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_run public.render_runs%rowtype;
  v_kind text;
  v_job_found boolean;
  v_run_found boolean;
begin

  select * into v_run from public.render_runs r
    where r.workspace_id = p_workspace and r.claimed_by = p_worker and r.status = 'running'
    order by r.started_at
    limit 1
    for update;
  if found then
    v_kind := 'render';
  else
    select * into v_job from public.production_jobs j
      where j.workspace_id = p_workspace and j.claimed_by = p_worker and j.status = 'preparing'
      order by j.updated_at
      limit 1
      for update;
    if found then
      v_kind := 'prepare';
    end if;
  end if;

  if v_kind is null then
    select * into v_job from public.production_jobs j
      where j.workspace_id = p_workspace and j.status = 'preparing' and j.claimed_by is null
      order by j.created_at, j.id
      limit 1
      for update skip locked;
    v_job_found := found;
    select * into v_run from public.render_runs r
      where r.workspace_id = p_workspace and r.status = 'queued'
      order by r.created_at, r.id
      limit 1
      for update skip locked;
    v_run_found := found;
    if v_job_found and (not v_run_found or v_job.created_at <= v_run.created_at) then
      v_kind := 'prepare';
    elsif v_run_found then
      v_kind := 'render';
    else
      return null;
    end if;
  end if;

  -- 새 수령과 재시작 복구 모두 여기서 updated_at=now()(복구 직후 만료되지 않게, 리뷰 반영 3)
  if v_kind = 'prepare' then
    update public.production_jobs j
      set claimed_by = p_worker, updated_at = now()
      where j.id = v_job.id
      returning * into v_job;
  else
    update public.render_runs r
      set status = 'running', claimed_by = p_worker,
          started_at = coalesce(r.started_at, now()), updated_at = now()
      where r.id = v_run.id
      returning * into v_run;
    select * into v_job from public.production_jobs j where j.id = v_run.job_id;
  end if;

  return jsonb_build_object(
    'kind', v_kind,
    'id', case when v_kind = 'render' then v_run.id else v_job.id end,
    'job_id', v_job.id,
    'job_kind', 'general',
    'format', v_job.format,
    'preset_version',
      case when v_kind = 'render' then v_run.preset_version else v_job.preset_version end,
    'lang', case when v_kind = 'render' then v_run.lang end,
    'source_start_sec', v_job.source_start_sec,
    'segment_len_sec', v_job.segment_len_sec,
    'source_kind', v_job.source_kind,
    'spec', case when v_kind = 'render' then
      (select r.spec from public.edit_revisions r
        where r.id = v_run.revision_id and r.job_id = v_run.job_id) end);
end;
$$;
comment on function public.claim_production_task(uuid, uuid) is
  'W-05 제작 task 수령(재시작 복구·skip locked 1건·조건부 갱신) 한 트랜잭션. API 전용';

-- W-09 완료·실패 ------------------------------------------------------------------
-- 자산 크기 확인은 API가 RPC 전에 한다. 여기서는 목록 자산을 다시 확인하고(E6) ready로 바꾸며,
-- 목록에 없는 이 task의 pending 산출물 행을 지우고 그 경로를 돌려준다(Storage 삭제는 API).
create function public.finish_production_task(
  p_workspace uuid, p_worker uuid, p_kind text, p_task uuid, p_status text,
  p_asset_ids uuid[], p_meta jsonb, p_error_stage text, p_error_code text,
  p_spec jsonb, p_validation jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_run public.render_runs%rowtype;
  v_ids uuid[] := coalesce(p_asset_ids, '{}');
  v_allowed text[];
  v_found integer;
  v_paths text[];
  v_rev uuid;
begin
  if p_kind = 'prepare' then
    select * into v_job from public.production_jobs j
      where j.id = p_task and j.workspace_id = p_workspace
      for update;
    if not found then
      raise exception '작업이 없습니다' using errcode = 'NR009';
    end if;
    if v_job.claimed_by is distinct from p_worker or v_job.status <> 'preparing' then
      raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
        using errcode = 'NR010';
    end if;
    v_allowed := array['source', 'analysis', 'sheet'];
  elsif p_kind = 'render' then
    select * into v_run from public.render_runs r
      where r.id = p_task and r.workspace_id = p_workspace;
    if not found then
      raise exception '렌더 실행이 없습니다' using errcode = 'NR009';
    end if;
    select * into v_job from public.production_jobs j where j.id = v_run.job_id for update;
    select * into v_run from public.render_runs r where r.id = p_task for update;
    if v_run.claimed_by is distinct from p_worker or v_run.status <> 'running' then
      raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_run.status)
        using errcode = 'NR010';
    end if;
    v_allowed := array['output_mp4', 'report', 'hook_audio'];
  else
    raise exception '작업 종류가 올바르지 않습니다' using errcode = 'NR012';
  end if;

  if p_status = 'done' then
    -- E6: 같은 job·pending·허용 kind·created_by=워커·render_run_id=run(prepare는 null)
    select count(*) into v_found from public.production_assets a
      where a.id = any(v_ids) and a.job_id = v_job.id and a.workspace_id = p_workspace
        and a.status = 'pending' and a.kind = any(v_allowed) and a.created_by = p_worker
        and a.render_run_id is not distinct from (case when p_kind = 'render' then v_run.id end);
    if v_found <> (select count(distinct x) from unnest(v_ids) x) then
      raise exception '산출물 목록이 올바르지 않습니다' using errcode = 'NR012';
    end if;
    if p_kind = 'prepare' and (
         (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'source') <> 1
      or (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'analysis') <> 1
      or not exists (select 1 from public.production_assets a where a.id = any(v_ids) and a.kind = 'sheet')) then
      raise exception '필수 산출물이 없습니다' using errcode = 'NR012';
    end if;
    if p_kind = 'render' and (
         (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'output_mp4') <> 1
      or (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'report') <> 1
      or (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'hook_audio') > 1) then
      raise exception '필수 산출물이 없습니다' using errcode = 'NR012';
    end if;
    update public.production_assets a set status = 'ready' where a.id = any(v_ids);
  end if;

  -- 목록에 없는 이 task의 pending 산출물(실패면 전부)을 지운다
  with gone as (
    delete from public.production_assets a
      where a.job_id = v_job.id and a.workspace_id = p_workspace and a.status = 'pending'
        and a.kind = any(v_allowed)
        and a.render_run_id is not distinct from (case when p_kind = 'render' then v_run.id end)
        and not (a.id = any(v_ids))
      returning a.storage_path
  )
  select coalesce(array_agg(g.storage_path), '{}') into v_paths from gone g;

  if p_kind = 'prepare' then
    if p_status = 'done' then
      if v_job.current_revision_id is null then
        insert into public.edit_revisions (workspace_id, job_id, lang, rev_no, spec, validation)
        values (p_workspace, v_job.id, v_job.lang, 1, coalesce(p_spec, '{}'),
                coalesce(p_validation, '{"errors": [], "warnings": []}'))
        returning id into v_rev;
      end if;
      update public.production_jobs j
        set status = 'review', source_meta = coalesce(p_meta, j.source_meta),
            current_revision_id = coalesce(j.current_revision_id, v_rev), updated_at = now()
        where j.id = v_job.id;
    else
      update public.production_jobs j
        set status = 'failed', failed_stage = 'prepare', error_code = p_error_code,
            updated_at = now()
        where j.id = v_job.id;
    end if;
  else
    if p_status = 'done' then
      update public.render_runs r
        set status = 'done', progress_pct = 100, finished_at = now(), updated_at = now(),
            mp4_asset_id = (select a.id from public.production_assets a
                            where a.id = any(v_ids) and a.kind = 'output_mp4'),
            report_asset_id = (select a.id from public.production_assets a
                               where a.id = any(v_ids) and a.kind = 'report'),
            hook_audio_asset_id = (select a.id from public.production_assets a
                                   where a.id = any(v_ids) and a.kind = 'hook_audio')
        where r.id = v_run.id;
      if v_run.lang = 'ko' and v_job.status = 'rendering' then
        update public.production_jobs j
          set status = 'inspect', updated_at = now()
          where j.id = v_job.id;
      end if;
    else
      update public.render_runs r
        set status = 'failed', error_stage = p_error_stage, error_code = p_error_code,
            finished_at = now(), updated_at = now()
        where r.id = v_run.id;
      if v_run.lang = 'ko' and v_job.status = 'rendering' then
        if p_error_code in ('hook_too_long', 'text_too_long') then
          -- 편집안·훅 문구 보존, 편집 검토로 되돌림(사유는 run.error_code)
          update public.production_jobs j
            set status = 'review', failed_stage = null, error_code = null, updated_at = now()
            where j.id = v_job.id;
        else
          update public.production_jobs j
            set status = 'failed', failed_stage = p_error_stage, error_code = p_error_code,
                updated_at = now()
            where j.id = v_job.id;
        end if;
      end if;
    end if;
  end if;

  return jsonb_build_object('status', p_status, 'deleted_paths', to_jsonb(v_paths));
end;
$$;
comment on function public.finish_production_task(uuid, uuid, text, uuid, text, uuid[], jsonb, text, text, jsonb, jsonb) is
  'W-09 제작 task 완료·실패(자산 ready·pending 정리·상태 전이·첫 리비전) 한 트랜잭션. API 전용';

-- 권한: service_role만 실행 ---------------------------------------------------------
revoke execute on function public.expire_production_offline(uuid) from public, anon, authenticated;
grant execute on function public.expire_production_offline(uuid) to service_role;
revoke execute on function public._render_run_json(public.render_runs, boolean) from public, anon, authenticated;
grant execute on function public._render_run_json(public.render_runs, boolean) to service_role;
revoke execute on function public.request_render_run(uuid, uuid, uuid, uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.request_render_run(uuid, uuid, uuid, uuid, text, text) to service_role;
revoke execute on function public.retry_render_run(uuid, uuid, uuid, uuid) from public, anon, authenticated;
grant execute on function public.retry_render_run(uuid, uuid, uuid, uuid) to service_role;
revoke execute on function public.claim_production_task(uuid, uuid) from public, anon, authenticated;
grant execute on function public.claim_production_task(uuid, uuid) to service_role;
revoke execute on function public.finish_production_task(uuid, uuid, text, uuid, text, uuid[], jsonb, text, text, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.finish_production_task(uuid, uuid, text, uuid, text, uuid[], jsonb, text, text, jsonb, jsonb)
  to service_role;
