-- task-031 URL 원본(000019) 테스트: W-05 claim이 rights_confirmed URL 작업에만 source_url을 준다.
-- 근거: tasks/task-031.md#착수-결정 G8, docs/04_API.md#W-05. 나머지 claim 동작은 production_render_test.sql.
begin;
create extension if not exists pgtap with schema extensions;
select plan(5);

insert into public.workspaces (id, name) values
  ('dddddddd-0031-4000-8000-000000000001', 'url-w1');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('dddddddd-0031-4000-8000-0000000000c1', 'dddddddd-0031-4000-8000-000000000001', 'U', 'h'),
  ('dddddddd-0031-4000-8000-0000000000c2', 'dddddddd-0031-4000-8000-000000000001', 'V', 'h');

-- j1: URL·권리 확인(먼저 생성), j2: 업로드 작업에 source_url이 남아 있는 경우
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, status,
   source_kind, source_url, rights_confirmed, created_at, updated_at) values
  ('dddddddd-0031-4000-8000-000000000011', 'dddddddd-0031-4000-8000-000000000001', 'j1', 60, 'category-1080-v1', 'k1',
   'preparing', 'url', 'https://www.youtube.com/watch?v=abcdefghijk', true, now() - interval '2 minutes', now()),
  ('dddddddd-0031-4000-8000-000000000012', 'dddddddd-0031-4000-8000-000000000001', 'j2', 60, 'category-1080-v1', 'k2',
   'preparing', 'upload', 'https://www.youtube.com/watch?v=zzzzzzzzzzz', false, now() - interval '1 minute', now());

-- 1. URL·권리 확인 작업: source_url 전달
select is(
  public.claim_production_task('dddddddd-0031-4000-8000-000000000001', 'dddddddd-0031-4000-8000-0000000000c1')->>'source_url',
  'https://www.youtube.com/watch?v=abcdefghijk', 'claim: url·rights_confirmed → source_url 전달');

-- 2. 재시작 복구도 같은 값
select is(
  public.claim_production_task('dddddddd-0031-4000-8000-000000000001', 'dddddddd-0031-4000-8000-0000000000c1')->>'source_kind',
  'url', 'claim 복구: 같은 url task');

-- 3. 업로드 작업: source_url 키 없음(000017 반환 모양 유지)
select ok(
  (select not (t ? 'source_url') and t->>'job_id' = 'dddddddd-0031-4000-8000-000000000012'
   from (select public.claim_production_task('dddddddd-0031-4000-8000-000000000001',
     'dddddddd-0031-4000-8000-0000000000c2') as t) s),
  'claim: upload 작업은 source_url 키 없음');

-- 4. 권한은 그대로(service_role만)
select ok(
  not has_function_privilege('authenticated', 'public.claim_production_task(uuid, uuid)', 'execute')
  and not has_function_privilege('anon', 'public.claim_production_task(uuid, uuid)', 'execute'),
  'claim: authenticated·anon 실행 불가 유지');
select ok(
  has_function_privilege('service_role', 'public.claim_production_task(uuid, uuid)', 'execute'),
  'claim: service_role 실행 가능 유지');

select * from finish();
rollback;
