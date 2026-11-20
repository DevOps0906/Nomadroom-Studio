-- task-050: 일본어판(ja) 렌더 — A-15 ja 분기·A-16 ja 거부·W-05 ja 능력 워커만 수령
-- 근거: tasks/task-050.md#착수-결정 K2·K3·K8, docs/04_API.md#A-15·#A-16·#W-05
-- 적용된 파일(000017·000020·000024)은 수정하지 않고 같은 시그니처로 create or replace 한다.
-- 권한·주석은 원본 그대로(create or replace는 grant를 유지한다).
-- W-09 완료·실패(000023)·오프라인 만료(000017)는 이미 ko run만 job 상태를 바꾼다(변경 없음).

-- A-15 렌더 요청(000017 본문 + ja 분기) -------------------------------------------
-- ja(K2): job 잠금 안에서 리비전 = current_ja_revision_id·승인됨, derived_from = 현재 ko 리비전이고
--   그 ko가 승인됨(TOCTOU 방지). job 상태는 inspect·done만, 바꾸지 않는다(render_runs로만 추적).
create or replace function public.request_render_run(
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

  if p_lang = 'ja' then
    if v_job.status not in ('inspect', 'done') then
      raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
        using errcode = 'NR010';
    end if;
    select * into v_rev from public.edit_revisions r
      where r.id = p_revision and r.job_id = p_job;
    if not found or v_rev.approved_at is null or v_rev.lang <> 'ja'
       or v_rev.id is distinct from v_job.current_ja_revision_id then
      raise exception '현재 승인된 리비전이 아닙니다' using errcode = 'NR012';
    end if;
    if v_rev.derived_from is distinct from v_job.current_revision_id
       or not exists (select 1 from public.edit_revisions k
                      where k.id = v_job.current_revision_id and k.job_id = p_job
                        and k.lang = 'ko' and k.approved_at is not null) then
      raise exception '원본(ko) 편집안이 바뀌었습니다. 일본어판을 다시 만드세요.'
        using errcode = 'NR010';
    end if;
  else
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

  if p_lang = 'ko' then
    update public.production_jobs j
      set status = 'rendering', failed_stage = null, error_code = null, updated_at = now()
      where j.id = p_job;
  end if;
  return public._render_run_json(v_run, true);
end;
$$;
comment on function public.request_render_run(uuid, uuid, uuid, uuid, text, text) is
  'A-15 렌더 요청(멱등 키·승인 현재 리비전·부분 unique) 한 트랜잭션. ko: review→rendering, ja: inspect·done에서 job 상태 불변(task-050). API 전용';

-- A-16 재시도(000020 본문 + ja 거부, K3) -------------------------------------------
create or replace function public.retry_render_run(p_workspace uuid, p_job uuid, p_user uuid, p_run uuid)
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
  -- K3: ja run은 재시도 없음(job 상태를 바꾸지 않으므로 A-15로 다시 요청)
  if v_old.lang <> 'ko' then
    raise exception '일본어판 렌더는 다시 렌더 요청하세요.' using errcode = 'NR010';
  end if;
  -- null이 조건을 우회하지 않게 coalesce(리뷰 반영 6)
  if v_old.status <> 'failed'
     or coalesce(v_old.error_code, '') in ('hook_too_long', 'text_too_long', 'tts_failed')
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

-- W-05 수령(000024 본문 + ja 능력, K8) ---------------------------------------------
-- ja run은 capabilities에 'ja'를 알린 워커에게만 새로 준다(재시작 복구는 조건 없음).
create or replace function public.claim_production_task(
  p_workspace uuid, p_worker uuid, p_formats text[]
)
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
  v_shopping boolean := 'shopping' = any(coalesce(p_formats, '{}'));
  v_ja boolean := 'ja' = any(coalesce(p_formats, '{}'));
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
    -- R4: 쇼핑 job은 워커가 'shopping' 형식을 알릴 때만 새로 내준다(재시작 복구는 조건 없음)
    select * into v_job from public.production_jobs j
      where j.workspace_id = p_workspace and j.status = 'preparing' and j.claimed_by is null
        and (v_shopping or j.kind <> 'shopping')
      order by j.created_at, j.id
      limit 1
      for update skip locked;
    v_job_found := found;
    select * into v_run from public.render_runs r
      where r.workspace_id = p_workspace and r.status = 'queued'
        and (v_ja or r.lang <> 'ja')
        and (v_shopping or not exists (select 1 from public.production_jobs sj
                                         where sj.id = r.job_id and sj.kind = 'shopping'))
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

  -- 새 수령과 재시작 복구 모두 여기서 updated_at=now()(복구 직후 만료되지 않게)
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
    'job_kind', v_job.kind,
    'format', v_job.format,
    'preset_version',
      case when v_kind = 'render' then v_run.preset_version else v_job.preset_version end,
    'lang', case when v_kind = 'render' then v_run.lang end,
    'source_start_sec', v_job.source_start_sec,
    'segment_len_sec', v_job.segment_len_sec,
    'source_kind', v_job.source_kind,
    'spec', case when v_kind = 'render' then
      (select r.spec from public.edit_revisions r
        where r.id = v_run.revision_id and r.job_id = v_run.job_id) end)
    || case when v_kind = 'prepare' and v_job.source_kind = 'url' and v_job.rights_confirmed
         and v_job.source_url is not null
       then jsonb_build_object('source_url', v_job.source_url) else '{}'::jsonb end;
end;
$$;
