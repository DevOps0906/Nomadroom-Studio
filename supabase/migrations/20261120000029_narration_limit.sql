-- task-058: 쇼핑 녹음 상한을 작업 전체 8개(ko 4 + ja 4, 가정)로 올린다.
-- 자산에 lang이 없어 언어별 상한 대신 작업 전체 상한. 본문은 000023 복사, narration 숫자만 4 → 8.
-- 문장별 4개(리비전당)는 API spec 검증이 지킨다. 다른 kind 상한(10) 불변.

create or replace function public.production_assets_source_limit()
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
  -- 쇼핑 다건 업로드 상한(pending 포함, 가정): 원본 10·사진 10·녹음 작업 전체 8(ko 4 + ja 4, task-058)
  if v_job.kind = 'shopping' and (tg_op = 'INSERT' or old.kind is distinct from new.kind) and (
      select count(*) from public.production_assets a
        where a.job_id = new.job_id and a.kind = new.kind and a.id <> new.id)
      >= (case new.kind when 'narration' then 8 else 10 end) then
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
