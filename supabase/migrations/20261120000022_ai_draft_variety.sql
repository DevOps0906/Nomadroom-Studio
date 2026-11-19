-- task-040: 예능형 AI 초안 — reserve_ai_draft 형식 조건만 교체(000018 본문 위 diff)
-- 근거: tasks/task-040.md#착수-결정 A1. variety 허용(shopping은 계속 NR010, task-048),
-- variety이면서 작업 lang≠ko면 계수 없이 NR010(409). 그 밖의 판정 순서·멱등·상한·60초는 000018 그대로.

create or replace function public.reserve_ai_draft(
  p_workspace uuid, p_job uuid, p_user uuid, p_key text, p_limit integer
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_req jsonb;
  v_base public.edit_revisions%rowtype;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;

  -- 같은 키 재요청: 기존 결과(횟수 증가 없음). 다른 작업의 키면 409
  select e into v_req from jsonb_array_elements(v_job.ai_draft_requests) e
    where e ->> 'key' = p_key;
  if v_req is not null then
    if v_req ->> 'status' = 'pending' then
      if (v_req ->> 'created_at')::timestamptz > now() - interval '5 minutes' then
        raise exception '같은 요청을 처리 중입니다' using errcode = 'NR018';
      end if;
      -- 5분 넘은 pending은 실패로 확정(같은 키 재요청이 영구 409가 되지 않게)
      v_req := public._ai_draft_set(p_job, p_key,
        jsonb_build_object('status', 'failed', 'finished_at', now()));
    end if;
    return public._ai_draft_json(v_req, v_job.ai_draft_count, true);
  end if;
  if exists (select 1 from public.production_jobs j
             where j.workspace_id = p_workspace and j.id <> p_job
               and j.ai_draft_requests @> jsonb_build_array(jsonb_build_object('key', p_key))) then
    raise exception '다른 작업에 쓴 멱등 키입니다' using errcode = 'NR011';
  end if;

  if v_job.status <> 'review' then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
      using errcode = 'NR010';
  end if;
  -- A1: category·variety만(shopping은 task-048). variety는 ko 작업만
  if v_job.format not in ('category', 'variety') then
    raise exception '%', format('이 형식(%s)은 AI 초안을 지원하지 않습니다.', v_job.format)
      using errcode = 'NR010';
  end if;
  if v_job.format = 'variety' and v_job.lang <> 'ko' then
    raise exception '%', format('이 언어(%s)의 예능형 작업은 AI 초안을 지원하지 않습니다.', v_job.lang)
      using errcode = 'NR010';
  end if;
  if v_job.ai_draft_count >= p_limit then
    raise exception 'AI 초안 횟수를 모두 썼습니다' using errcode = 'NR016';
  end if;
  if exists (select 1 from jsonb_array_elements(v_job.ai_draft_requests) e
             where (e ->> 'created_at')::timestamptz > now() - interval '60 seconds') then
    raise exception 'AI 초안을 너무 자주 요청했습니다' using errcode = 'NR017';
  end if;

  select * into v_base from public.edit_revisions r
    where r.id = v_job.current_revision_id and r.job_id = p_job;
  v_req := jsonb_build_object(
    'key', p_key, 'status', 'pending', 'base_rev_no', v_base.rev_no,
    'base_revision_id', v_base.id, 'base_updated_at', v_base.updated_at, 'revision_id', null,
    'requested_by', p_user, 'created_at', now());
  update public.production_jobs j
    set ai_draft_count = j.ai_draft_count + 1,
        ai_draft_requests = j.ai_draft_requests || jsonb_build_array(v_req)
    where j.id = p_job;
  return public._ai_draft_json(v_req, v_job.ai_draft_count + 1, false);
end;
$$;
comment on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer) is
  'A-14 AI 초안 예약(review·category|variety(ko)·작업당 상한·60초 간격·멱등 키, 횟수+1) 한 트랜잭션. API 전용';

revoke execute on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer) to service_role;
