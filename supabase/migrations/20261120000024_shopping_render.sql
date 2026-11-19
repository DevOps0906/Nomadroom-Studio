-- task-045: 쇼핑 렌더러 연결 — claim 쇼핑 보류 해제(워커가 지원 형식을 알릴 때만)
-- 근거: tasks/task-045.md#착수-결정 R4, docs/04_API.md#W-05
-- 000023 claim 본문 위에 p_formats(워커 capabilities) 조건만 얹는다. 000023 파일은 수정하지 않는다.
-- 2인자 claim은 지원 형식 없음('{}')과 같은 래퍼로 남긴다(구버전 워커·기존 테스트 호환).

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
revoke execute on function public.claim_production_task(uuid, uuid, text[]) from public, anon, authenticated;
grant execute on function public.claim_production_task(uuid, uuid, text[]) to service_role;

-- 2인자: 지원 형식 없음(쇼핑 새 수령 없음, 000023과 같은 동작)
create or replace function public.claim_production_task(p_workspace uuid, p_worker uuid)
returns jsonb
language sql
security definer
set search_path = ''
as $$
  select public.claim_production_task(p_workspace, p_worker, '{}'::text[]);
$$;
revoke execute on function public.claim_production_task(uuid, uuid) from public, anon, authenticated;
grant execute on function public.claim_production_task(uuid, uuid) to service_role;
