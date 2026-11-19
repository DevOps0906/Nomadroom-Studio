-- task-044: 쇼핑 API 보조 — 원본 계보·원본 개수 트리거·쇼핑 prepare 완료 조건·claim 쇼핑 보류
-- 근거: tasks/task-044.md#착수-결정 P1~P5·P9, docs/04_API.md#A-10·#A-11·#W-05·#W-07·#W-09
-- RPC 본문은 직전 최신(finish 000020, claim 000021) 위에 diff만 얹는다. reserve_ai_draft는 건드리지 않는다.
-- 오류 SQLSTATE: 23505 = 원본 개수 위반(일반 ready 2건째·쇼핑 11건째) → API 409,
--   NR010 = 상태 불가(원본 ready 전환·삭제, 참조 자산 삭제, 원본 없는 준비 시작) → 409,
--   NR012 = 산출물 목록 → 400(000017 목록을 잇는다).

-- P1 계보: 원본 파생 산출물(source·analysis·sheet) → 같은 작업의 source_upload ---------------
alter table public.production_assets
  add column parent_asset_id uuid,
  add constraint production_assets_parent_fk foreign key (parent_asset_id, job_id)
    references public.production_assets (id, job_id),
  add constraint production_assets_parent_kind_chk
    check (parent_asset_id is null or kind in ('source', 'analysis', 'sheet'));
comment on column public.production_assets.parent_asset_id is
  '원본 파생 산출물(source·analysis·sheet)의 부모 source_upload(같은 작업, 쇼핑 필수)';
create index production_assets_parent_asset_id_idx on public.production_assets (parent_asset_id);

create function public.production_assets_parent_source()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
      select 1 from public.production_assets p
        where p.id = new.parent_asset_id and p.job_id = new.job_id and p.kind = 'source_upload') then
    raise exception 'production_assets.parent_asset_id must reference a source_upload' using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function public.production_assets_parent_source() from public, anon, authenticated;
create trigger production_assets_parent_source
  before insert or update of parent_asset_id on public.production_assets
  for each row when (new.parent_asset_id is not null)
  execute function public.production_assets_parent_source();

-- P2 원본 개수: 부분 unique 인덱스 → job 행 잠금 트리거 ------------------------------------
-- general: ready 1건(000016 인덱스와 같은 23505). shopping: pending 포함 10건 이하(가정).
-- ready 전환은 job이 draft·failed(prepare)일 때만(준비 중·이후에는 원본 집합이 바뀌지 않는다).
drop index public.production_assets_one_ready_source_uidx;

create function public.production_assets_source_limit()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
begin
  select * into v_job from public.production_jobs j where j.id = new.job_id for update;
  if not found then
    return new;  -- 작업 FK가 거부한다
  end if;
  -- 쇼핑 다건 업로드 상한(pending 포함, 가정): 원본 10·사진 10·문장별 녹음 4(리뷰 반영 4)
  if v_job.kind = 'shopping' and (tg_op = 'INSERT' or old.kind is distinct from new.kind) and (
      select count(*) from public.production_assets a
        where a.job_id = new.job_id and a.kind = new.kind and a.id <> new.id)
      >= (case new.kind when 'narration' then 4 else 10 end) then
    raise exception '작업당 업로드 상한을 넘었습니다' using errcode = '23505';
  end if;
  if new.kind = 'source_upload' and new.status = 'ready'
     and (tg_op = 'INSERT' or old.status is distinct from 'ready') then
    if not (v_job.status = 'draft' or (v_job.status = 'failed' and v_job.failed_stage = 'prepare')) then
      raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status) using errcode = 'NR010';
    end if;
    if v_job.kind = 'general' and exists (
        select 1 from public.production_assets a
          where a.job_id = new.job_id and a.kind = 'source_upload' and a.status = 'ready'
            and a.id <> new.id) then
      raise exception '이미 업로드된 원본이 있습니다' using errcode = '23505';
    end if;
  end if;
  return new;
end;
$$;
revoke all on function public.production_assets_source_limit() from public, anon, authenticated;
create trigger production_assets_source_limit
  before insert or update of status, kind on public.production_assets
  for each row when (new.kind in ('source_upload', 'image', 'narration'))
  execute function public.production_assets_source_limit();

-- P9 ready 원본 삭제는 draft·failed(prepare)에서만(A-11 준비 시작과 job 행 잠금으로 직렬화).
-- 작업 삭제 cascade는 job 행이 이미 없어 통과한다.
create function public.production_assets_source_delete_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
begin
  select * into v_job from public.production_jobs j where j.id = old.job_id for update;
  if found and not (v_job.status = 'draft' or (v_job.status = 'failed' and v_job.failed_stage = 'prepare')) then
    raise exception '%', format('현재 상태(%s)에서는 할 수 없습니다.', v_job.status) using errcode = 'NR010';
  end if;
  return old;
end;
$$;
revoke all on function public.production_assets_source_delete_guard() from public, anon, authenticated;
create trigger production_assets_source_delete_guard
  before delete on public.production_assets
  for each row when (old.kind = 'source_upload' and old.status = 'ready')
  execute function public.production_assets_source_delete_guard();

-- 리뷰 반영 6: image·bgm·narration 삭제는 job 행 잠금 뒤 현재 리비전(ko·ja) 참조를 다시 본다
-- (A-12 저장·A-13 승인 RPC와 같은 job 잠금으로 직렬화, 참조 중이면 NR010).
create function public.production_assets_ref_delete_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_job public.production_jobs%rowtype;
  v_id text := old.id::text;
begin
  select * into v_job from public.production_jobs j where j.id = old.job_id for update;
  if found and exists (
      select 1 from public.edit_revisions r
        where r.job_id = v_job.id
          and r.id in (v_job.current_revision_id, v_job.current_ja_revision_id)
          and (r.spec ->> 'bgm_asset_id' = v_id
            or r.spec #>> '{voice,narration_asset_id}' = v_id
            or (jsonb_typeof(r.spec #> '{voice,narration_asset_ids}') = 'array'
                and r.spec #> '{voice,narration_asset_ids}' ? v_id)
            or (jsonb_typeof(r.spec -> 'cuts') = 'array' and exists (
                  select 1 from jsonb_array_elements(r.spec -> 'cuts') c
                    where c ->> 'source_asset_id' = v_id)))) then
    raise exception '편집안에서 쓰는 자산입니다' using errcode = 'NR010';
  end if;
  return old;
end;
$$;
revoke all on function public.production_assets_ref_delete_guard() from public, anon, authenticated;
create trigger production_assets_ref_delete_guard
  before delete on public.production_assets
  for each row when (old.kind in ('image', 'bgm', 'narration'))
  execute function public.production_assets_ref_delete_guard();

-- 리뷰 반영 3: 업로드 작업이 preparing이 될 때 ready 원본이 있어야 한다(A-11과 원본 삭제 경합).
-- job 행 갱신이 행 잠금을 잡고, 삭제 가드도 같은 행을 잠그므로 둘 중 하나만 통과한다.
create function public.production_jobs_prepare_source()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
      select 1 from public.production_assets a
        where a.job_id = new.id and a.kind = 'source_upload' and a.status = 'ready') then
    raise exception '업로드된 원본이 없습니다' using errcode = 'NR010';
  end if;
  return new;
end;
$$;
revoke all on function public.production_jobs_prepare_source() from public, anon, authenticated;
create trigger production_jobs_prepare_source
  before update of status on public.production_jobs
  for each row when (new.status = 'preparing' and old.status is distinct from 'preparing'
                     and new.source_kind = 'upload')
  execute function public.production_jobs_prepare_source();

-- P3 W-09 finish: 쇼핑 prepare done은 ready 원본마다 source·analysis 정확히 1건·sheet ≥1(parent로 묶음)
-- 000020 본문에서 prepare 필수 자산 검사만 kind별로 나눈다.
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
    if p_kind = 'prepare' and v_job.kind <> 'shopping' and (
         (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'source') <> 1
      or (select count(*) from public.production_assets a where a.id = any(v_ids) and a.kind = 'analysis') <> 1
      or not exists (select 1 from public.production_assets a where a.id = any(v_ids) and a.kind = 'sheet')) then
      raise exception '필수 산출물이 없습니다' using errcode = 'NR012';
    end if;
    -- task-044 P3: 쇼핑은 모든 산출물이 ready 원본을 parent로 갖고, ready 원본마다 한 벌씩
    if p_kind = 'prepare' and v_job.kind = 'shopping' and (
         not exists (select 1 from public.production_assets u
           where u.job_id = v_job.id and u.kind = 'source_upload' and u.status = 'ready')
      or exists (select 1 from public.production_assets a
           where a.id = any(v_ids) and not exists (
             select 1 from public.production_assets u
               where u.id = a.parent_asset_id and u.job_id = v_job.id
                 and u.kind = 'source_upload' and u.status = 'ready'))
      or exists (select 1 from public.production_assets u
           where u.job_id = v_job.id and u.kind = 'source_upload' and u.status = 'ready' and (
                (select count(*) from public.production_assets a
                   where a.id = any(v_ids) and a.parent_asset_id = u.id and a.kind = 'source') <> 1
             or (select count(*) from public.production_assets a
                   where a.id = any(v_ids) and a.parent_asset_id = u.id and a.kind = 'analysis') <> 1
             or not exists (select 1 from public.production_assets a
                   where a.id = any(v_ids) and a.parent_asset_id = u.id and a.kind = 'sheet')))) then
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

-- P4 W-05 claim: task-045(쇼핑 렌더러) 전까지 kind=shopping job의 prepare·render를 내주지 않는다 ----
-- 000021 본문에서 새 수령 조건 두 곳에 kind 조건만 추가(045에서 해제).
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
        and j.kind <> 'shopping'
      order by j.created_at, j.id
      limit 1
      for update skip locked;
    v_job_found := found;
    select * into v_run from public.render_runs r
      where r.workspace_id = p_workspace and r.status = 'queued'
        and not exists (select 1 from public.production_jobs sj
                          where sj.id = r.job_id and sj.kind = 'shopping')
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
    -- task-031: source_url 키는 URL 작업 prepare일 때만 붙인다(그 외 반환 모양은 000017 그대로)
    || case when v_kind = 'prepare' and v_job.source_kind = 'url' and v_job.rights_confirmed
         and v_job.source_url is not null
       then jsonb_build_object('source_url', v_job.source_url) else '{}'::jsonb end;
end;
$$;
