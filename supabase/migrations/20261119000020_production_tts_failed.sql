-- task-030: TTS 실패(tts_failed)를 hook_too_long·text_too_long과 같게 다룬다(tasks/task-030.md#착수-결정 I1).
-- W-09 failed(tts_failed) → job review 복귀(편집안 보존), A-16 재시도 거부(첨부 음성으로 바꿔 다시 승인).
-- 000017의 두 함수만 create or replace(본문은 코드 목록 한 줄씩만 다름). 시그니처·권한·주석은 그대로.

-- A-16 재시도 ---------------------------------------------------------------------
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

-- W-09 완료·실패 -----------------------------------------------------------------
create or replace function public.finish_production_task(
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
        if p_error_code in ('hook_too_long', 'text_too_long', 'tts_failed') then
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
