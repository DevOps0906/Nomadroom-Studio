-- task-059: A-12 저장 낙관적 잠금 강화(base_updated_at, ko·ja)
-- 근거: tasks/task-059.md#착수-결정 L2·L3. 미승인 리비전을 같은 rev_no로 동시에 저장하면 앞선 편집이
-- 유실되던 문제 → 잠금 안에서 리비전 updated_at을 함께 비교(다르면 NR011 → 409).
-- 기존 6인자 함수는 drop 후 새 시그니처로 다시 만든다(오버로드 0개). 본문은 000016·000027 정본 복사.

drop function public.save_production_revision(uuid, uuid, uuid, integer, jsonb, jsonb);
drop function public.save_ja_revision(uuid, uuid, uuid, integer, jsonb, jsonb);

create function public.save_production_revision(
  p_workspace uuid, p_job uuid, p_user uuid, p_base_rev_no integer, p_base_updated_at timestamptz,
  p_spec jsonb, p_validation jsonb
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
  if not (v_job.status in ('review', 'inspect')
          or (v_job.status = 'failed' and v_job.failed_stage in ('audio', 'render'))) then
    raise exception '편집안을 저장할 수 없는 상태입니다' using errcode = 'NR010';
  end if;
  if v_job.current_revision_id is null then
    raise exception '편집안 리비전이 없습니다' using errcode = 'NR010';
  end if;
  select * into v_rev from public.edit_revisions r
    where r.id = v_job.current_revision_id and r.job_id = p_job;
  if not found then
    raise exception '편집안 리비전이 없습니다' using errcode = 'NR010';
  end if;
  if v_rev.rev_no <> p_base_rev_no or v_rev.updated_at <> p_base_updated_at then
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
      (workspace_id, job_id, lang, rev_no, schema_version, spec, origin, validation, created_by)
    values (
      p_workspace, p_job, v_rev.lang,
      (select max(r.rev_no) + 1 from public.edit_revisions r
        where r.job_id = p_job and r.lang = v_rev.lang),
      v_rev.schema_version, p_spec, 'user', p_validation, p_user
    )
    returning * into v_rev;
    update public.production_jobs j set current_revision_id = v_rev.id where j.id = p_job;
  end if;

  if v_job.status in ('inspect', 'failed') then
    update public.production_jobs j
      set status = 'review', failed_stage = null, error_code = null, updated_at = now()
      where j.id = p_job;
  end if;

  return jsonb_build_object(
    'id', v_rev.id, 'rev_no', v_rev.rev_no, 'spec', v_rev.spec, 'origin', v_rev.origin,
    'validation', v_rev.validation, 'approved_at', v_rev.approved_at,
    'updated_at', v_rev.updated_at);
end;
$$;
comment on function public.save_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb) is
  'A-12 편집안 저장(낙관적 잠금 rev_no·updated_at·오류 있어도 저장·inspect/failed→review) 한 트랜잭션. API 전용';

create function public.save_ja_revision(
  p_workspace uuid, p_job uuid, p_user uuid, p_base_rev_no integer, p_base_updated_at timestamptz,
  p_spec jsonb, p_validation jsonb
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
  if v_rev.rev_no <> p_base_rev_no or v_rev.updated_at <> p_base_updated_at then
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
    'derived_from', v_rev.derived_from, 'updated_at', v_rev.updated_at);
end;
$$;
comment on function public.save_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb) is
  'A-12 ja 편집안 저장(현재 승인 ko·ja 렌더 없음·낙관적 잠금 rev_no·updated_at, job 상태 불변) 한 트랜잭션. API 전용';

revoke all on function public.save_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.save_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)
  to service_role;
revoke all on function public.save_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.save_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)
  to service_role;

-- L1: A-14(AI 초안)·A-20(번역) 결과 JSON에도 리비전 updated_at(다음 저장의 base) ---------------
-- 000025 _ai_draft_json·000027 _translate_json 본문 그대로 + updated_at(시그니처 같음 → replace).
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
        'validation', r.validation, 'approved_at', r.approved_at, 'updated_at', r.updated_at)
      from public.edit_revisions r where r.id = (p_req ->> 'revision_id')::uuid));
$$;

create or replace function public._translate_json(p_req jsonb, p_count integer, p_replay boolean)
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
        'validation', r.validation, 'approved_at', r.approved_at, 'derived_from', r.derived_from,
        'updated_at', r.updated_at)
      from public.edit_revisions r where r.id = (p_req ->> 'revision_id')::uuid));
$$;

revoke all on function public._ai_draft_json(jsonb, integer, boolean) from public, anon, authenticated;
grant execute on function public._ai_draft_json(jsonb, integer, boolean) to service_role;
revoke all on function public._translate_json(jsonb, integer, boolean) from public, anon, authenticated;
grant execute on function public._translate_json(jsonb, integer, boolean) to service_role;
