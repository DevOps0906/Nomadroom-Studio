-- task-022: 제작 작업 API 보조(A-09 멱등 키, A-12 저장·A-13 승인 원자적 RPC)
-- 근거: tasks/task-022.md#착수-결정 D1·D2·D3, docs/04_API.md#A-09·#A-12·#A-13
-- 오류 SQLSTATE: NR009 = 작업 없음(타 워크스페이스 포함) → 404,
--               NR010 = 상태 불가(허용 상태 아님·리비전 없음·이미 승인) → 409,
--               NR011 = 낙관적 잠금 불일치(base_rev_no·rev_no·updated_at) → 409.

-- D1 멱등 키 ------------------------------------------------------------------
alter table public.production_jobs add column idempotency_key text;
update public.production_jobs set idempotency_key = id::text where idempotency_key is null;
alter table public.production_jobs alter column idempotency_key set not null;
alter table public.production_jobs
  add constraint production_jobs_workspace_id_idempotency_key_key unique (workspace_id, idempotency_key);
comment on column public.production_jobs.idempotency_key is 'A-09 Idempotency-Key(같은 키 재요청은 기존 작업 반환)';

-- D5 업로드 원본은 작업당 ready 1건(동시 complete 경합 방지, 위반 시 API 409) -------------
create unique index production_assets_one_ready_source_uidx on public.production_assets (job_id)
  where kind = 'source_upload' and status = 'ready';

-- D2·D3 A-12 리비전 저장 --------------------------------------------------------
-- 허용 상태: review·inspect·failed(failed_stage ∈ audio·render). 현재 리비전이 미승인이면 그 행을 갱신,
-- 승인본이면 새 rev_no로 만들고 current_revision_id를 옮긴다. inspect·failed는 review로 되돌린다.
create function public.save_production_revision(
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
    'validation', v_rev.validation, 'approved_at', v_rev.approved_at);
end;
$$;
comment on function public.save_production_revision(uuid, uuid, uuid, integer, jsonb, jsonb) is
  'A-12 편집안 저장(낙관적 잠금·오류 있어도 저장·inspect/failed→review) 한 트랜잭션. API 전용';

-- D2 A-13 승인 ------------------------------------------------------------------
-- API가 재검증할 때 읽은 리비전 updated_at과 같을 때만 승인한다(사이에 저장되면 409).
create function public.approve_production_revision(
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
  if v_job.status <> 'review' or v_job.current_revision_id is null then
    raise exception '승인할 수 없는 상태입니다' using errcode = 'NR010';
  end if;
  select * into v_rev from public.edit_revisions r
    where r.id = v_job.current_revision_id and r.job_id = p_job
    for update;
  if not found then
    raise exception '편집안 리비전이 없습니다' using errcode = 'NR010';
  end if;
  if v_rev.rev_no <> p_rev_no or v_rev.updated_at <> p_updated_at then
    raise exception '다른 곳에서 먼저 수정되었습니다' using errcode = 'NR011';
  end if;
  if v_rev.approved_at is not null then
    raise exception '이미 승인된 리비전입니다' using errcode = 'NR010';
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
comment on function public.approve_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb) is
  'A-13 편집안 승인(review·현재 리비전·updated_at 일치) 한 트랜잭션. API 전용';

revoke execute on function public.save_production_revision(uuid, uuid, uuid, integer, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.save_production_revision(uuid, uuid, uuid, integer, jsonb, jsonb)
  to service_role;
revoke execute on function public.approve_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)
  from public, anon, authenticated;
grant execute on function public.approve_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)
  to service_role;
