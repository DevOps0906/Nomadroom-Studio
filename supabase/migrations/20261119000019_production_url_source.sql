-- task-031 URL 원본(W-05): claim_production_task가 prepare task에 source_url을 돌려준다.
-- 근거: tasks/task-031.md#착수-결정(G2·G8), docs/04_API.md#W-05.
-- source_url 키는 prepare·source_kind='url'·rights_confirmed=true일 때만(그 외 키 없음). render에는 주지 않는다.
-- 000017의 claim 함수만 create or replace(반환 객체에 조건부 source_url 키만 추가). 시그니처·권한·주석은 그대로.

create or replace function public.claim_production_task(p_workspace uuid, p_worker uuid)
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
        where r.id = v_run.revision_id and r.job_id = v_run.job_id) end)
    -- task-031: source_url 키는 URL 작업 prepare일 때만 붙인다(그 외 반환 모양은 000017 그대로)
    || case when v_kind = 'prepare' and v_job.source_kind = 'url' and v_job.rights_confirmed
         and v_job.source_url is not null
       then jsonb_build_object('source_url', v_job.source_url) else '{}'::jsonb end;
end;
$$;
