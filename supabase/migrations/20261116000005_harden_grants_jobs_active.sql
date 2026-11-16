-- task-002 리뷰 반영: jobs 활성 상태에 retrying 포함, 브라우저 역할 권한 최소화

-- 1. 같은 워크스페이스·종류의 활성 작업(queued·running·retrying)은 하나만
drop index public.jobs_one_active_per_kind_idx;
create unique index jobs_one_active_per_kind_idx on public.jobs (workspace_id, kind)
  where status in ('queued', 'running', 'retrying');

-- 2. 기존 테이블: anon·authenticated 권한 전부 제거 후 authenticated에 조회만(workers 제외)
revoke all on all tables in schema public from anon, authenticated;
grant select on all tables in schema public to authenticated;
revoke select on public.workers from authenticated;

-- 3. 앞으로 만들 객체: 브라우저 역할·public에 기본 권한을 주지 않는다(필요한 권한은 마이그레이션에서 명시 grant)
alter default privileges in schema public revoke all on tables from anon, authenticated, public;
alter default privileges in schema public revoke all on functions from anon, authenticated, public;
alter default privileges in schema public revoke all on sequences from anon, authenticated, public;
-- 함수의 public execute는 전역 기본값이라 스키마 단위 revoke로는 지워지지 않는다(PostgreSQL 규칙)
alter default privileges revoke execute on functions from public;
