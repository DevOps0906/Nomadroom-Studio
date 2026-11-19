-- task-042: 유형·분야·brief·제휴·권리·리비전 언어 스키마(쇼핑쇼츠·일본어판 확장)
-- 근거: docs/05_DATA_MODEL.md#쇼핑-확장, tasks/plan-shopping-japanese.md#팀장-설계-결정, tasks/task-042.md#착수-결정(S1~S8)
-- 기존 행은 kind=general·lang=ko 기본값. RPC는 claim의 job_kind만 칼럼 값으로 바꾼다(S3, 000019 본문 위 diff).
-- kind·lang별 동작(쇼핑 원본 다건·ja 렌더·ai_draft 형식)은 task-044·049가 새 마이그레이션으로 교체한다.

-- 제휴 링크 배열 검사(S7·리뷰 1): 최대 20건, [{lang: ko|ja, partner: 비어 있지 않은 문자열,
-- url: https://, 공백·제어 문자 없음, 2048자 이하}]
create function public.production_affiliates_valid(p jsonb)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select case when jsonb_typeof(p) <> 'array' then false
    when jsonb_array_length(p) > 20 then false
    else not exists (
      select 1 from jsonb_array_elements(p) e
        where not (
          jsonb_typeof(e) = 'object'
          and coalesce(e ->> 'lang', '') in ('ko', 'ja')
          and jsonb_typeof(e -> 'partner') = 'string' and length(btrim(e ->> 'partner')) > 0
          and jsonb_typeof(e -> 'url') = 'string' and (e ->> 'url') ~ '^https://[^[:space:][:cntrl:]]+$'
          and length(e ->> 'url') <= 2048))
  end;
$$;
comment on function public.production_affiliates_valid(jsonb) is
  'production_jobs.affiliates check용: 배열 ≤20·원소 {lang ko|ja, partner, url https:// ≤2048자}';
revoke all on function public.production_affiliates_valid(jsonb) from public, anon, authenticated;
-- check 식의 함수도 실행 권한을 검사하므로 쓰기 역할(service_role)에 부여(리뷰 5)
grant execute on function public.production_affiliates_valid(jsonb) to service_role;

-- 제작 작업: 유형·분야·brief·제휴·댓글 키워드 ---------------------------------
alter table public.production_jobs
  add column kind text not null default 'general' check (kind in ('general', 'shopping')),
  add column vertical text check (vertical in ('product', 'travel')),
  add column brief jsonb,
  add column affiliates jsonb not null default '[]',
  add column comment_keyword text,
  add column current_ja_revision_id uuid;
comment on column public.production_jobs.kind is '유형 general(조회수)·shopping(제휴 전환). 생성 후 변경 불가(트리거)';
comment on column public.production_jobs.vertical is '쇼핑 분야 product·travel(shopping만 필수, 그 외 null)';
comment on column public.production_jobs.brief is '쇼핑 brief(제품·여행 입력 + target 메모, shopping만)';
comment on column public.production_jobs.affiliates is '제휴 링크 [{lang, partner, url https}] — 운영자 수동 입력, 게시 문구에만 사용';
comment on column public.production_jobs.comment_keyword is '댓글 유도 단어(게시 문구용)';
comment on column public.production_jobs.current_ja_revision_id is '일본어판 현재 리비전(current_revision_id는 ko)';

alter table public.production_jobs drop constraint production_jobs_format_check;
alter table public.production_jobs
  add constraint production_jobs_format_check check (format in ('category', 'variety', 'shopping')),
  add constraint production_jobs_kind_format_chk check ((kind = 'shopping') = (format = 'shopping')),
  add constraint production_jobs_vertical_chk check ((kind = 'shopping') = (vertical is not null)),
  add constraint production_jobs_brief_chk
    check (brief is null or (kind = 'shopping' and jsonb_typeof(brief) = 'object'
                             and pg_column_size(brief) <= 32768)),
  add constraint production_jobs_affiliates_chk check (public.production_affiliates_valid(affiliates));

-- kind 변경 거부(S7)
create function public.production_jobs_kind_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'production_jobs.kind is immutable' using errcode = '23514';
end;
$$;
revoke all on function public.production_jobs_kind_immutable() from public, anon, authenticated;
create trigger production_jobs_kind_immutable
  before update of kind on public.production_jobs
  for each row when (old.kind is distinct from new.kind)
  execute function public.production_jobs_kind_immutable();

-- 후보 소속 일관성(S5, task-020 리뷰 후속): (candidate_id, workspace_id) 복합 FK ----
do $$
begin
  if exists (
    select 1 from public.production_jobs j join public.candidates c on c.id = j.candidate_id
      where c.workspace_id <> j.workspace_id) then
    raise exception 'production_jobs.candidate_id: 다른 워크스페이스 후보를 참조하는 행이 있음';
  end if;
end;
$$;
alter table public.candidates add constraint candidates_id_workspace_id_key unique (id, workspace_id);
alter table public.production_jobs drop constraint production_jobs_candidate_id_fkey;
alter table public.production_jobs
  add constraint production_jobs_candidate_fk foreign key (candidate_id, workspace_id)
    references public.candidates (id, workspace_id) on delete set null (candidate_id);

-- 편집안 리비전: 언어·파생(S6) ---------------------------------------------
alter table public.edit_revisions drop constraint edit_revisions_lang_check;
alter table public.edit_revisions
  add constraint edit_revisions_lang_check check (lang in ('ko', 'ja')),
  add column derived_from uuid,
  add constraint edit_revisions_id_job_id_lang_key unique (id, job_id, lang);
comment on column public.edit_revisions.derived_from is 'ja 리비전의 원본 ko 리비전(같은 작업, ja ⇔ not null)';
alter table public.edit_revisions
  add constraint edit_revisions_derived_from_chk check ((lang = 'ja') = (derived_from is not null)),
  add constraint edit_revisions_derived_from_fk foreign key (derived_from, job_id)
    references public.edit_revisions (id, job_id);
create index edit_revisions_derived_from_idx on public.edit_revisions (derived_from);

alter table public.production_jobs
  add constraint production_jobs_current_ja_revision_fk foreign key (current_ja_revision_id, id)
    references public.edit_revisions (id, job_id) on delete set null (current_ja_revision_id);
create index production_jobs_current_ja_revision_idx on public.production_jobs (current_ja_revision_id);

-- 참조 리비전 언어 강제(리뷰 4): derived_from → ko, current_ja_revision_id → ja.
-- 리비전 lang은 생성 후 바뀌지 않는다(API가 바꾸지 않음)는 전제의 트리거 검사.
create function public.edit_revisions_derived_from_lang()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.derived_from is not null and not exists (
      select 1 from public.edit_revisions r where r.id = new.derived_from and r.lang = 'ko') then
    raise exception 'edit_revisions.derived_from must reference a ko revision' using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function public.edit_revisions_derived_from_lang() from public, anon, authenticated;
create trigger edit_revisions_derived_from_lang
  before insert or update of derived_from on public.edit_revisions
  for each row when (new.derived_from is not null)
  execute function public.edit_revisions_derived_from_lang();

create function public.production_jobs_current_ja_revision_lang()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
      select 1 from public.edit_revisions r where r.id = new.current_ja_revision_id and r.lang = 'ja') then
    raise exception 'production_jobs.current_ja_revision_id must reference a ja revision' using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function public.production_jobs_current_ja_revision_lang() from public, anon, authenticated;
create trigger production_jobs_current_ja_revision_lang
  before insert or update of current_ja_revision_id on public.production_jobs
  for each row when (new.current_ja_revision_id is not null)
  execute function public.production_jobs_current_ja_revision_lang();

-- 렌더 실행: ja 허용 + run 언어 = 리비전 언어(S1·S6) ------------------------
alter table public.render_runs drop constraint render_runs_lang_check;
alter table public.render_runs add constraint render_runs_lang_check check (lang in ('ko', 'ja'));
alter table public.render_runs drop constraint render_runs_revision_fk;
alter table public.render_runs
  add constraint render_runs_revision_fk foreign key (revision_id, job_id, lang)
    references public.edit_revisions (id, job_id, lang);

-- 제작 자산: bgm·image, 권리 기록(S1·S7) ------------------------------------
alter table public.production_assets drop constraint production_assets_kind_check;
alter table public.production_assets
  add constraint production_assets_kind_check check (kind in (
    'source_upload', 'source', 'analysis', 'sheet', 'hook_audio', 'narration',
    'output_mp4', 'report', 'transcript', 'bgm', 'image')),
  add column rights jsonb,
  add constraint production_assets_rights_chk check (
    rights is null or (
      jsonb_typeof(rights) = 'object'
      and (rights -> 'basis' is null or jsonb_typeof(rights -> 'basis') = 'null'
           or (rights ->> 'basis') in
             ('own', 'licensed', 'permission', 'quote', 'platform_audio', 'ai_generated'))
      and ((rights ->> 'source_url') is null
           or (rights ->> 'source_url') ~ '^https?://[^[:space:][:cntrl:]]+$')
      and pg_column_size(rights) <= 8192));
comment on column public.production_assets.rights is
  '자산 권리 {basis, source_url, author, has_person, portrait_consent, note, gen?} — 쇼핑 필수 여부는 승인 때 API가 검사';

-- Storage: 이미지 mime 추가(S1, 000015는 on conflict do nothing이라 update) ----
update storage.buckets
  set allowed_mime_types = allowed_mime_types || array(
    select m from unnest(array['image/png', 'image/webp']) m
      where not (m = any (allowed_mime_types)))
  where id = 'production';

-- W-05 claim: job_kind를 칼럼 값으로(S3) — 000019 본문에서 'job_kind' 한 줄만 변경 ----
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
