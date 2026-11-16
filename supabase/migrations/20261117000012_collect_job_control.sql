-- task-008: 수집 job 재시도·중지 RPC. API(service_role)만 사용한다.
-- 근거: tasks/task-008.md#구현 결정, docs/02_ARCHITECTURE.md#3-3
-- 오류 SQLSTATE: NR003 = 다른 워크스페이스(또는 없는) 수집 작업
--               NR005 = 이 작업의 조회 상한 도달(lookup_count 또는 수집 수 ≥ params.limit)
--               NR006 = 재시도 불가(failed 아님·상한 3회·중지 요청됨·남은 프로필 없음) / 이미 종료(중지)
--               NR007 = 같은 워크스페이스에 다른 활성 수집 작업, 22023 = 잘못된 인자.
-- jobs.error의 `stopped_by_user`는 000011 제약에 이미 있다.

-- 재시도: failed → retrying. lookup_count는 초기화하지 않는다(task-007 계약).
-- resume_from_profile_id = profile_ids 순서로 처음 done이 아닌 프로필. 그 프로필부터의 failed 행은 pending.
create function public.retry_collect_job(p_workspace uuid, p_job uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_job public.jobs%rowtype;
  v_limit integer;
  v_collected integer;
  v_resume uuid;
  v_resume_pos integer;
begin
  if p_workspace is null or p_job is null then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;

  select * into v_job from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect'
    for update;
  if not found then
    raise exception '이 워크스페이스의 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;
  if v_job.status <> 'failed' or v_job.retry_count >= 3 or v_job.stop_requested then
    raise exception '재시도 불가' using errcode = 'NR006';
  end if;

  -- params.limit이 1~200 정수면 그 값, 아니면 200(apply_collect_batch·API claim 응답과 같은 규칙).
  -- AND는 평가 순서가 보장되지 않으므로 중첩 CASE로 숫자일 때만 형 변환한다(문자열이어도 22P02 없음).
  v_limit := case
    when jsonb_typeof(v_job.params -> 'limit') = 'number' then
      case
        when (v_job.params ->> 'limit')::numeric between 1 and 200
          and (v_job.params ->> 'limit')::numeric % 1 = 0
        then (v_job.params ->> 'limit')::integer
        else 200
      end
    else 200
  end;
  select coalesce(sum(r.collected_count), 0)::integer into v_collected
    from public.job_profile_runs r where r.job_id = p_job;
  if v_job.lookup_count >= v_limit or v_collected >= v_limit then
    raise exception '이 작업의 조회 상한 도달' using errcode = 'NR005';
  end if;

  perform 1 from public.jobs j
    where j.workspace_id = p_workspace and j.kind = 'collect' and j.id <> p_job
      and j.status in ('queued', 'running', 'retrying');
  if found then
    raise exception '다른 수집 작업이 진행 중입니다' using errcode = 'NR007';
  end if;

  -- 행이 없는 프로필(실행 행 생성 실패)도 done이 아닌 것으로 본다.
  select t.pid, (t.ord - 1)::integer into v_resume, v_resume_pos
    from unnest(v_job.profile_ids) with ordinality as t(pid, ord)
    where not exists (
      select 1 from public.job_profile_runs r
        where r.job_id = p_job and r.profile_id = t.pid and r.status = 'done'
    )
    order by t.ord
    limit 1;
  if v_resume is null then
    raise exception '재시도할 프로필이 없습니다' using errcode = 'NR006';
  end if;

  update public.job_profile_runs r
    set status = 'pending', updated_at = now()
    where r.job_id = p_job and r.status = 'failed' and r.position >= v_resume_pos;

  update public.jobs j
    set status = 'retrying',
        retry_count = j.retry_count + 1,
        error = null,
        finished_at = null,
        claimed_by = null,
        params = j.params || jsonb_build_object('resume_from_profile_id', v_resume)
    where j.id = p_job
    returning * into v_job;

  return jsonb_build_object(
    'id', v_job.id, 'status', v_job.status, 'stop_requested', v_job.stop_requested,
    'retry_count', v_job.retry_count
  );
end;
$$;
comment on function public.retry_collect_job(uuid, uuid) is
  '수집 job 재시도(failed → retrying, 처음 done이 아닌 프로필부터). API 전용';

-- 중지: queued·retrying → 즉시 stopped, running → stop_requested만(워커가 W-04로 마감).
create function public.stop_collect_job(p_workspace uuid, p_job uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_job public.jobs%rowtype;
begin
  if p_workspace is null or p_job is null then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;

  select * into v_job from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect'
    for update;
  if not found then
    raise exception '이 워크스페이스의 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;

  if v_job.status in ('queued', 'retrying') then
    update public.jobs j
      set status = 'stopped', error = 'stopped_by_user', finished_at = now()
      where j.id = p_job
      returning * into v_job;
  elsif v_job.status = 'running' then
    update public.jobs j set stop_requested = true where j.id = p_job
      returning * into v_job;
  else
    raise exception '이미 종료된 작업입니다' using errcode = 'NR006';
  end if;

  return jsonb_build_object(
    'id', v_job.id, 'status', v_job.status, 'stop_requested', v_job.stop_requested,
    'retry_count', v_job.retry_count
  );
end;
$$;
comment on function public.stop_collect_job(uuid, uuid) is
  '수집 job 중지(queued·retrying → stopped, running → stop_requested). API 전용';

revoke execute on function public.retry_collect_job(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.stop_collect_job(uuid, uuid) from public, anon, authenticated;
grant execute on function public.retry_collect_job(uuid, uuid) to service_role;
grant execute on function public.stop_collect_job(uuid, uuid) to service_role;
