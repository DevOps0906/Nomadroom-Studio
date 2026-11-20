-- task-049: 일본어판(ja) 리비전 — A-20 파생·번역 예약/생성/실패, A-12 ja 저장, A-13 ja 승인 RPC
-- 근거: tasks/task-049.md#착수-결정 J2·J5·J9, docs/04_API.md#A-12·#A-13·#A-20
-- 000016(ko 저장·승인)·000018/000025(AI 초안)은 건드리지 않고 ja 전용 함수를 따로 둔다(J5).
-- 공통 허용 조건(J2): 현재 ko 리비전이 승인됨 + ja 렌더(render_runs lang=ja)가 queued·running 아님.
--   job 상태(status)는 어느 함수도 바꾸지 않는다.
-- 번역 호출(J9): AI 초안과 별도 카운터(translate_count)·별도 멱등 키 공간(translate_requests)·
--   별도 60초 규칙. 원소 {key, kind:"translate", status(pending·done·failed), ko_revision_id,
--   revision_id, requested_by, created_at, finished_at}. 5분 넘은 pending은 실패로 본다.
-- 오류 SQLSTATE(000016·000018을 잇는다): NR009 작업 없음 → 404, NR010 상태 불가 → 409,
--   NR011 낙관적 잠금 불일치·다른 작업의 멱등 키 → 409, NR012 입력 리비전이 현재 승인 ko가 아님 → 400,
--   NR016 작업당 상한 → 429 QUOTA_EXCEEDED, NR017 60초 내 새 키 → 429 RATE_LIMITED,
--   NR018 같은 키 처리 중 → 409.

alter table public.production_jobs
  add column translate_count integer not null default 0 check (translate_count >= 0),
  add column translate_requests jsonb not null default '[]'
    check (jsonb_typeof(translate_requests) = 'array');
comment on column public.production_jobs.translate_count is
  'A-20 번역 호출 횟수(성공·실패 모두, AI 초안 ai_draft_count와 별도)';
comment on column public.production_jobs.translate_requests is
  'A-20 번역 요청 기록(kind=translate·멱등 키·상태·원본 ko 리비전·결과 ja 리비전·시각). 쓰기는 API RPC만';

-- 공통 허용 조건(내부) --------------------------------------------------------------
-- 잠근 작업의 id·현재 ko 리비전으로 ja 쓰기 가능 여부를 본다. 불가면 NR010.
-- (행 타입 인자는 PostgREST 계산 필드로 노출되므로 uuid 두 개를 받는다)
create function public._ja_writable(p_job uuid, p_ko uuid)
returns void
language plpgsql
stable
set search_path = ''
as $$
begin
  if p_ko is null or not exists (
      select 1 from public.edit_revisions r
        where r.id = p_ko and r.job_id = p_job
          and r.lang = 'ko' and r.approved_at is not null) then
    raise exception '원본(ko) 편집안이 승인된 상태에서만 일본어판을 다룰 수 있습니다'
      using errcode = 'NR010';
  end if;
  if exists (select 1 from public.render_runs r
             where r.job_id = p_job and r.lang = 'ja' and r.status in ('queued', 'running')) then
    raise exception '일본어판 렌더가 진행 중입니다' using errcode = 'NR010';
  end if;
end;
$$;

-- 결과 JSON(리비전·횟수) ------------------------------------------------------------
create function public._translate_json(p_req jsonb, p_count integer, p_replay boolean)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select jsonb_build_object(
    'replay', p_replay,
    'request_status', p_req ->> 'status',
    'translate_count', p_count,
    'revision', (select jsonb_build_object(
        'id', r.id, 'rev_no', r.rev_no, 'spec', r.spec, 'origin', r.origin,
        'validation', r.validation, 'approved_at', r.approved_at, 'derived_from', r.derived_from)
      from public.edit_revisions r where r.id = (p_req ->> 'revision_id')::uuid));
$$;

-- 요청 원소 상태 바꾸기(내부) -------------------------------------------------------
create function public._translate_set(p_job uuid, p_key text, p_patch jsonb)
returns jsonb
language sql
set search_path = ''
as $$
  update public.production_jobs j
    set translate_requests = (
      select coalesce(jsonb_agg(case when e ->> 'key' = p_key then e || p_patch else e end
                                order by o), '[]'::jsonb)
      from jsonb_array_elements(j.translate_requests) with ordinality as t(e, o))
    where j.id = p_job
    returning (select e from jsonb_array_elements(j.translate_requests) e where e ->> 'key' = p_key);
$$;

-- A-20 예약: 잠금·멱등·입력 리비전·허용 조건·상한·60초, 횟수+1 후 커밋(Claude 호출은 밖) ------
create function public.reserve_translation(
  p_workspace uuid, p_job uuid, p_user uuid, p_key text, p_revision uuid, p_limit integer
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_req jsonb;
begin
  -- 리뷰 반영(3): 같은 워크스페이스·같은 키의 예약을 작업과 무관하게 직렬화(다른 작업 동시 예약 경합)
  perform pg_advisory_xact_lock(
    hashtextextended('reserve_translation:' || p_workspace::text || ':' || p_key, 0));
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;

  select e into v_req from jsonb_array_elements(v_job.translate_requests) e
    where e ->> 'key' = p_key;
  if v_req is not null then
    if v_req ->> 'status' = 'pending' then
      if (v_req ->> 'created_at')::timestamptz > now() - interval '5 minutes' then
        raise exception '같은 요청을 처리 중입니다' using errcode = 'NR018';
      end if;
      v_req := public._translate_set(p_job, p_key,
        jsonb_build_object('status', 'failed', 'finished_at', now()));
    end if;
    return public._translate_json(v_req, v_job.translate_count, true);
  end if;
  if exists (select 1 from public.production_jobs j
             where j.workspace_id = p_workspace and j.id <> p_job
               and j.translate_requests @> jsonb_build_array(jsonb_build_object('key', p_key))) then
    raise exception '다른 작업에 쓴 멱등 키입니다' using errcode = 'NR011';
  end if;

  -- J2: 파생 원본은 현재 ko 리비전이고 승인된 경우만(과거 승인본 불가)
  if p_revision is distinct from v_job.current_revision_id or not exists (
      select 1 from public.edit_revisions r
        where r.id = p_revision and r.job_id = p_job and r.lang = 'ko'
          and r.approved_at is not null) then
    raise exception '현재 승인된 원본(ko) 리비전만 번역할 수 있습니다' using errcode = 'NR012';
  end if;
  perform public._ja_writable(v_job.id, v_job.current_revision_id);
  if v_job.translate_count >= p_limit then
    raise exception '번역 횟수를 모두 썼습니다' using errcode = 'NR016';
  end if;
  if exists (select 1 from jsonb_array_elements(v_job.translate_requests) e
             where (e ->> 'created_at')::timestamptz > now() - interval '60 seconds') then
    raise exception '번역을 너무 자주 요청했습니다' using errcode = 'NR017';
  end if;

  v_req := jsonb_build_object(
    'key', p_key, 'kind', 'translate', 'status', 'pending', 'ko_revision_id', p_revision,
    'revision_id', null, 'requested_by', p_user, 'created_at', now());
  update public.production_jobs j
    set translate_count = j.translate_count + 1,
        translate_requests = j.translate_requests || jsonb_build_array(v_req)
    where j.id = p_job;
  return public._translate_json(v_req, v_job.translate_count + 1, false);
end;
$$;
comment on function public.reserve_translation(uuid, uuid, uuid, text, uuid, integer) is
  'A-20 번역 예약(현재 승인 ko·ja 렌더 없음·작업당 상한·60초·멱등 키, 횟수+1, AI 초안과 별도) 한 트랜잭션. API 전용';

-- A-20 ja 리비전 생성: 항상 새 rev_no(기존 ja 편집 보존), derived_from=예약한 ko 리비전 ------------
create function public.create_ja_translation(
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
  v_ko public.edit_revisions%rowtype;
  v_rev public.edit_revisions%rowtype;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select e into v_req from jsonb_array_elements(v_job.translate_requests) e
    where e ->> 'key' = p_key;
  if v_req is null or v_req ->> 'status' <> 'pending' then
    raise exception '처리 중인 번역 요청이 없습니다' using errcode = 'NR010';
  end if;
  -- 호출 중 ko 현재 리비전이 바뀌면(새 저장·교체) 파생하지 않는다
  if v_job.current_revision_id is distinct from (v_req ->> 'ko_revision_id')::uuid then
    raise exception '번역하는 동안 원본(ko) 편집안이 바뀌었습니다. 다시 시도하세요.'
      using errcode = 'NR010';
  end if;
  perform public._ja_writable(v_job.id, v_job.current_revision_id);
  select * into v_ko from public.edit_revisions r where r.id = v_job.current_revision_id;

  insert into public.edit_revisions
    (workspace_id, job_id, lang, rev_no, schema_version, spec, origin, validation, created_by,
     derived_from)
  values (
    p_workspace, p_job, 'ja',
    coalesce((select max(r.rev_no) from public.edit_revisions r
              where r.job_id = p_job and r.lang = 'ja'), 0) + 1,
    v_ko.schema_version, p_spec, 'ai_draft', p_validation, p_user, v_ko.id
  )
  returning * into v_rev;
  update public.production_jobs j set current_ja_revision_id = v_rev.id where j.id = p_job;
  v_req := public._translate_set(p_job, p_key,
    jsonb_build_object('status', 'done', 'revision_id', v_rev.id, 'finished_at', now()));
  return public._translate_json(v_req, v_job.translate_count, false);
end;
$$;
comment on function public.create_ja_translation(uuid, uuid, uuid, text, jsonb, jsonb) is
  'A-20 ja 리비전 생성(새 rev_no·origin=ai_draft·derived_from=현재 승인 ko·현재 ja 이동, job 상태 불변) 한 트랜잭션. API 전용';

create function public.fail_translation(p_workspace uuid, p_job uuid, p_key text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform 1 from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
      and exists (select 1 from jsonb_array_elements(j.translate_requests) e
                  where e ->> 'key' = p_key and e ->> 'status' = 'pending')
    for update;
  if found then
    perform public._translate_set(p_job, p_key,
      jsonb_build_object('status', 'failed', 'finished_at', now()));
  end if;
end;
$$;
comment on function public.fail_translation(uuid, uuid, text) is
  'A-20 번역 실패 기록(pending → failed). API 전용';

-- A-12 ja 저장: 현재 ja 리비전 기준 낙관적 잠금, 미승인이면 갱신·승인본이면 새 rev_no(같은 derived_from) --
create function public.save_ja_revision(
  p_workspace uuid, p_job uuid, p_user uuid, p_base_rev_no integer, p_spec jsonb, p_validation jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_rev public.edit_revisions%rowtype;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select * into v_rev from public.edit_revisions r
    where r.id = v_job.current_ja_revision_id and r.job_id = p_job and r.lang = 'ja';
  if not found then
    raise exception '일본어판 리비전이 없습니다' using errcode = 'NR010';
  end if;
  perform public._ja_writable(v_job.id, v_job.current_revision_id);
  if v_rev.rev_no <> p_base_rev_no then
    raise exception '다른 곳에서 먼저 수정되었습니다' using errcode = 'NR011';
  end if;

  if v_rev.approved_at is null then
    update public.edit_revisions r
      set spec = p_spec, validation = p_validation, updated_at = now()
      where r.id = v_rev.id and r.approved_at is null
      returning * into v_rev;
    if not found then
      raise exception '이미 승인된 리비전입니다' using errcode = 'NR010';
    end if;
  else
    insert into public.edit_revisions
      (workspace_id, job_id, lang, rev_no, schema_version, spec, origin, validation, created_by,
       derived_from)
    values (
      p_workspace, p_job, 'ja',
      (select max(r.rev_no) + 1 from public.edit_revisions r
        where r.job_id = p_job and r.lang = 'ja'),
      v_rev.schema_version, p_spec, 'user', p_validation, p_user, v_rev.derived_from
    )
    returning * into v_rev;
    update public.production_jobs j set current_ja_revision_id = v_rev.id where j.id = p_job;
  end if;

  return jsonb_build_object(
    'id', v_rev.id, 'rev_no', v_rev.rev_no, 'spec', v_rev.spec, 'origin', v_rev.origin,
    'validation', v_rev.validation, 'approved_at', v_rev.approved_at,
    'derived_from', v_rev.derived_from);
end;
$$;
comment on function public.save_ja_revision(uuid, uuid, uuid, integer, jsonb, jsonb) is
  'A-12 ja 편집안 저장(현재 승인 ko·ja 렌더 없음·낙관적 잠금, job 상태 불변) 한 트랜잭션. API 전용';

-- A-13 ja 승인: derived_from = 현재 승인 ko일 때만(원본 변경 시 차단, J8) ---------------------
create function public.approve_ja_revision(
  p_workspace uuid, p_job uuid, p_user uuid, p_rev_no integer, p_updated_at timestamptz,
  p_validation jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_rev public.edit_revisions%rowtype;
begin
  select * into v_job from public.production_jobs j
    where j.id = p_job and j.workspace_id = p_workspace
    for update;
  if not found then
    raise exception '작업이 없습니다' using errcode = 'NR009';
  end if;
  select * into v_rev from public.edit_revisions r
    where r.id = v_job.current_ja_revision_id and r.job_id = p_job and r.lang = 'ja'
    for update;
  if not found then
    raise exception '일본어판 리비전이 없습니다' using errcode = 'NR010';
  end if;
  perform public._ja_writable(v_job.id, v_job.current_revision_id);
  if v_rev.rev_no <> p_rev_no or v_rev.updated_at <> p_updated_at then
    raise exception '다른 곳에서 먼저 수정되었습니다' using errcode = 'NR011';
  end if;
  if v_rev.approved_at is not null then
    raise exception '이미 승인된 리비전입니다' using errcode = 'NR010';
  end if;
  if v_rev.derived_from is distinct from v_job.current_revision_id then
    raise exception '원본(ko) 편집안이 바뀌었습니다. 일본어판을 다시 만드세요.' using errcode = 'NR010';
  end if;

  update public.edit_revisions r
    set approved_at = now(), approved_by = p_user, validation = p_validation
    where r.id = v_rev.id
    returning * into v_rev;

  return jsonb_build_object(
    'id', v_rev.id, 'rev_no', v_rev.rev_no, 'approved_at', v_rev.approved_at,
    'approved_by', v_rev.approved_by);
end;
$$;
comment on function public.approve_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb) is
  'A-13 ja 편집안 승인(현재 승인 ko = derived_from·ja 렌더 없음·updated_at 일치, job 상태 불변) 한 트랜잭션. API 전용';

-- 권한: 전부 service_role(API)만 -------------------------------------------------------
revoke all on function public._ja_writable(uuid, uuid) from public, anon, authenticated;
grant execute on function public._ja_writable(uuid, uuid) to service_role;
revoke all on function public._translate_json(jsonb, integer, boolean) from public, anon, authenticated;
grant execute on function public._translate_json(jsonb, integer, boolean) to service_role;
revoke all on function public._translate_set(uuid, text, jsonb) from public, anon, authenticated;
grant execute on function public._translate_set(uuid, text, jsonb) to service_role;
revoke all on function public.reserve_translation(uuid, uuid, uuid, text, uuid, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_translation(uuid, uuid, uuid, text, uuid, integer) to service_role;
revoke all on function public.create_ja_translation(uuid, uuid, uuid, text, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.create_ja_translation(uuid, uuid, uuid, text, jsonb, jsonb) to service_role;
revoke all on function public.fail_translation(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.fail_translation(uuid, uuid, text) to service_role;
revoke all on function public.save_ja_revision(uuid, uuid, uuid, integer, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.save_ja_revision(uuid, uuid, uuid, integer, jsonb, jsonb) to service_role;
revoke all on function public.approve_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)
  from public, anon, authenticated;
grant execute on function public.approve_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)
  to service_role;
