-- task-048: 쇼핑 AI 대본 3안 — reserve_ai_draft 형식 조건(000022 본문 위 diff)·3안 저장·응답
-- 근거: tasks/task-048.md#착수-결정 S2·S5·S6, docs/04_API.md#A-14
-- 1) reserve_ai_draft: 000022 본문 그대로에 shopping 허용, shopping·variety는 ko 작업만(그 밖은 계수 없이 NR010).
-- 2) 3안·hook_type·글자 수·확인할 사실은 spec 밖, 요청 기록 원소(production_jobs.ai_draft_requests)의
--    variants·facts_to_check 키에 저장한다(워커·렌더 페이로드에 안 감). 멱등 replay도 같은 값을 돌려준다.
-- 3) create_ai_draft_revision: 6인자 함수를 지우고 p_variants·p_facts(기본 null)를 더한 8인자로 교체
--    (기본값 있는 오버로드를 함께 두면 PostgREST 이름 호출이 모호해진다). 본문은 000018 그대로 + 저장.

-- 결과 JSON: 000018 + variants·facts_to_check(쇼핑만 값, 그 밖은 null) -----------------------
create or replace function public._ai_draft_json(p_req jsonb, p_count integer, p_replay boolean)
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
    'variants', p_req -> 'variants',
    'facts_to_check', p_req -> 'facts_to_check',
    'revision', (select jsonb_build_object(
        'id', r.id, 'rev_no', r.rev_no, 'spec', r.spec, 'origin', r.origin,
        'validation', r.validation, 'approved_at', r.approved_at)
      from public.edit_revisions r where r.id = (p_req ->> 'revision_id')::uuid));
$$;

-- 예약: 000022 본문 + shopping(ko) 허용 -----------------------------------------------------
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
  -- task-040 A1·task-048 S2: category·variety·shopping. variety·shopping은 ko 작업만
  if v_job.format not in ('category', 'variety', 'shopping') then
    raise exception '%', format('이 형식(%s)은 AI 초안을 지원하지 않습니다.', v_job.format)
      using errcode = 'NR010';
  end if;
  if v_job.format = 'variety' and v_job.lang <> 'ko' then
    raise exception '%', format('이 언어(%s)의 예능형 작업은 AI 초안을 지원하지 않습니다.', v_job.lang)
      using errcode = 'NR010';
  end if;
  if v_job.format = 'shopping' and v_job.lang <> 'ko' then
    raise exception '%', format('이 언어(%s)의 쇼핑 작업은 AI 대본을 지원하지 않습니다.', v_job.lang)
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
  'A-14 AI 초안 예약(review·category|variety(ko)|shopping(ko)·작업당 상한·60초 간격·멱등 키, 횟수+1) 한 트랜잭션. API 전용';

-- 리비전 생성: 000018 본문 + 쇼핑 3안·확인할 사실을 요청 기록에 저장 ---------------------------
drop function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb);
create function public.create_ai_draft_revision(
  p_workspace uuid, p_job uuid, p_user uuid, p_key text, p_spec jsonb, p_validation jsonb,
  p_variants jsonb default null, p_facts jsonb default null
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
  if (p_variants is not null and jsonb_typeof(p_variants) <> 'array')
     or (p_facts is not null and jsonb_typeof(p_facts) <> 'array') then
    raise exception 'variants·facts_to_check는 배열이어야 합니다' using errcode = '22023';
  end if;
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
  -- 호출 중 사용자가 저장한 편집(같은 행 갱신·새 rev) 위로 AI 초안이 현재가 되지 않게
  if v_job.current_revision_id is distinct from (v_req ->> 'base_revision_id')::uuid
     or (select r.updated_at from public.edit_revisions r where r.id = v_job.current_revision_id)
        is distinct from (v_req ->> 'base_updated_at')::timestamptz then
    raise exception 'AI 초안을 만드는 동안 편집안이 바뀌었습니다. 다시 불러온 뒤 시도하세요.'
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
    jsonb_build_object('status', 'done', 'revision_id', v_rev.id, 'finished_at', now())
    || jsonb_strip_nulls(jsonb_build_object('variants', p_variants, 'facts_to_check', p_facts)));
  return public._ai_draft_json(v_req, v_job.ai_draft_count, false);
end;
$$;
comment on function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb, jsonb, jsonb) is
  'A-14 AI 초안 리비전 생성(review·새 rev_no·origin=ai_draft·현재 리비전 이동, 쇼핑 3안은 요청 기록에 저장) 한 트랜잭션. API 전용';

revoke execute on function public._ai_draft_json(jsonb, integer, boolean) from public, anon, authenticated;
grant execute on function public._ai_draft_json(jsonb, integer, boolean) to service_role;
revoke execute on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_draft(uuid, uuid, uuid, text, integer) to service_role;
revoke execute on function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb, jsonb, jsonb)
  to service_role;
