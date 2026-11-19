-- task-029: AI 초안(A-14) 호출 예약·리비전 생성 RPC와 멱등 키 기록
-- 근거: tasks/task-029.md#착수-결정 H1·H2·H3, docs/04_API.md#A-14, docs/01_PRD.md#7 Q7(작업당 3회)
-- 흐름: API가 reserve_ai_draft(잠금·검사·횟수+1·키 기록) 커밋 → 잠금 없이 Claude 호출 →
--       성공은 create_ai_draft_revision, 실패는 fail_ai_draft. 횟수는 성공·실패 모두 센다.
-- 멱등 키는 새 테이블 대신 작업 행의 ai_draft_requests(jsonb 배열, 작업당 상한 3건)에 둔다.
-- 원소: {key, status(pending·done·failed), base_rev_no, revision_id, created_at}.
-- 오류 SQLSTATE(000016·000017을 잇는다): NR009 작업 없음 → 404, NR010 상태 불가 → 409,
--   NR011 다른 작업의 멱등 키 → 409, NR016 작업당 상한 초과 → 429 QUOTA_EXCEEDED,
--   NR017 같은 작업 60초 내 새 키 → 429 RATE_LIMITED, NR018 같은 키 처리 중 → 409.

alter table public.production_jobs
  add column ai_draft_requests jsonb not null default '[]'
    check (jsonb_typeof(ai_draft_requests) = 'array');
comment on column public.production_jobs.ai_draft_requests is
  'A-14 AI 초안 요청 기록(멱등 키·상태·직전 rev_no·결과 리비전·시각). 쓰기는 API RPC만';

-- 결과 JSON(리비전·횟수·직전 rev_no) --------------------------------------------
create function public._ai_draft_json(p_req jsonb, p_count integer, p_replay boolean)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'replay', p_replay,
    'request_status', p_req ->> 'status',
    'ai_draft_count', p_count,
    'previous_rev_no', p_req -> 'base_rev_no',
    'revision', (select jsonb_build_object(
        'id', r.id, 'rev_no', r.rev_no, 'spec', r.spec, 'origin', r.origin,
        'validation', r.validation, 'approved_at', r.approved_at)
      from public.edit_revisions r where r.id = (p_req ->> 'revision_id')::uuid));
$$;

-- H2 예약: 잠금·검사·횟수+1·키 기록 후 커밋(Claude 호출은 이 트랜잭션 밖) --------------
create function public.reserve_ai_draft(
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
  v_base integer;
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
      raise exception '같은 요청을 처리 중입니다' using errcode = 'NR018';
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
  -- H3: variety 초안은 task-040
  if v_job.format <> 'category' then
    raise exception '%', format('이 형식(%s)은 AI 초안을 지원하지 않습니다.', v_job.format)
      using errcode = 'NR010';
  end if;
  if v_job.ai_draft_count >= p_limit then
    raise exception 'AI 초안 횟수를 모두 썼습니다' using errcode = 'NR016';
  end if;
  if exists (select 1 from jsonb_array_elements(v_job.ai_draft_requests) e
             where (e ->> 'created_at')::timestamptz > now() - interval '60 seconds') then
    raise exception 'AI 초안을 너무 자주 요청했습니다' using errcode = 'NR017';
  end if;

  select r.rev_no into v_base from public.edit_revisions r
    where r.id = v_job.current_revision_id and r.job_id = p_job;
  v_req := jsonb_build_object(
    'key', p_key, 'status', 'pending', 'base_rev_no', v_base, 'revision_id', null,
    'requested_by', p_user, 'created_at', now());
  update public.production_jobs j
    set ai_draft_count = j.ai_draft_count + 1,
        ai_draft_requests = j.ai_draft_requests || jsonb_build_array(v_req)
    where j.id = p_job;
  return public._ai_draft_json(v_req, v_job.ai_draft_count + 1, false);
end;
$$;
comment on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer) is
  'A-14 AI 초안 예약(review·category·작업당 상한·60초 간격·멱등 키, 횟수+1) 한 트랜잭션. API 전용';

-- 요청 원소 상태 바꾸기(내부) -------------------------------------------------------
create function public._ai_draft_set(p_job uuid, p_key text, p_patch jsonb)
returns jsonb
language sql
security definer
set search_path = ''
as $$
  update public.production_jobs j
    set ai_draft_requests = (
      select coalesce(jsonb_agg(case when e ->> 'key' = p_key then e || p_patch else e end
                                order by o), '[]'::jsonb)
      from jsonb_array_elements(j.ai_draft_requests) with ordinality as t(e, o))
    where j.id = p_job
    returning (select e from jsonb_array_elements(j.ai_draft_requests) e where e ->> 'key' = p_key);
$$;

-- H2 리비전 생성: 항상 새 rev_no, origin=ai_draft, 현재 리비전 이동(기존 편집은 보존) ---------
create function public.create_ai_draft_revision(
  p_workspace uuid, p_job uuid, p_user uuid, p_key text, p_spec jsonb, p_validation jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_req jsonb;
  v_rev public.edit_revisions%rowtype;
  v_schema integer;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select e into v_req from jsonb_array_elements(v_job.ai_draft_requests) e
    where e ->> 'key' = p_key;
  if v_req is null or v_req ->> 'status' <> 'pending' then
    raise exception '처리 중인 AI 초안 요청이 없습니다' using errcode = 'NR010';
  end if;
  if v_job.status <> 'review' then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status)
      using errcode = 'NR010';
  end if;

  select coalesce((select r.schema_version from public.edit_revisions r
                    where r.id = v_job.current_revision_id), 1) into v_schema;
  insert into public.edit_revisions
    (workspace_id, job_id, lang, rev_no, schema_version, spec, origin, validation, created_by)
  values (
    p_workspace, p_job, v_job.lang,
    coalesce((select max(r.rev_no) from public.edit_revisions r
              where r.job_id = p_job and r.lang = v_job.lang), 0) + 1,
    v_schema, p_spec, 'ai_draft', p_validation, p_user
  )
  returning * into v_rev;
  update public.production_jobs j set current_revision_id = v_rev.id where j.id = p_job;
  v_req := public._ai_draft_set(p_job, p_key,
    jsonb_build_object('status', 'done', 'revision_id', v_rev.id, 'finished_at', now()));
  return public._ai_draft_json(v_req, v_job.ai_draft_count, false);
end;
$$;
comment on function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb) is
  'A-14 AI 초안 리비전 생성(review·새 rev_no·origin=ai_draft·현재 리비전 이동) 한 트랜잭션. API 전용';

-- 실패 기록(횟수는 예약 때 이미 셌다) ---------------------------------------------
create function public.fail_ai_draft(p_workspace uuid, p_job uuid, p_key text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform 1 from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
      and exists (select 1 from jsonb_array_elements(j.ai_draft_requests) e
                  where e ->> 'key' = p_key and e ->> 'status' = 'pending')
    for update;
  if found then
    perform public._ai_draft_set(p_job, p_key,
      jsonb_build_object('status', 'failed', 'finished_at', now()));
  end if;
end;
$$;
comment on function public.fail_ai_draft(uuid, uuid, text) is
  'A-14 AI 초안 실패 기록(pending → failed). API 전용';

revoke execute on function public._ai_draft_json(jsonb, integer, boolean) from public, anon, authenticated;
grant execute on function public._ai_draft_json(jsonb, integer, boolean) to service_role;
revoke execute on function public._ai_draft_set(uuid, text, jsonb) from public, anon, authenticated;
grant execute on function public._ai_draft_set(uuid, text, jsonb) to service_role;
revoke execute on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer) to service_role;
revoke execute on function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb)
  to service_role;
revoke execute on function public.fail_ai_draft(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.fail_ai_draft(uuid, uuid, text) to service_role;
