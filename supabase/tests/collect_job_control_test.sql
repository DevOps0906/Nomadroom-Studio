-- task-008: retry_collect_job·stop_collect_job 권한·조건·오류 코드·실행 행 되돌리기 (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(37);

insert into public.workspaces (id, name) values
  ('dddddddd-0000-4000-8000-000000000001', 'control-ws'),
  ('dddddddd-0000-4000-8000-000000000002', 'control-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('dddddddd-0000-4000-8000-0000000000a1', 'dddddddd-0000-4000-8000-000000000001', 'p1', 'KR', 5),
  ('dddddddd-0000-4000-8000-0000000000a2', 'dddddddd-0000-4000-8000-000000000001', 'p2', 'KR', 5),
  ('dddddddd-0000-4000-8000-0000000000a3', 'dddddddd-0000-4000-8000-000000000001', 'p3', 'KR', 5);
insert into public.workers (id, workspace_id, name, token_hash) values
  ('dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-000000000001', 'w1', 'x');

-- f1: failed(재시도 대상, p1 done·p2 failed·p3 failed), f2: 다른 ws, f3: verify,
-- f4: failed·retry 3회, f5: failed·중지 요청, f6: failed·조회 상한(lookup 200),
-- f7: failed·수집 수 상한(limit 2), f8: failed·모든 프로필 done
insert into public.jobs (id, workspace_id, kind, status, profile_ids, params, idempotency_key,
                         claimed_by, retry_count, stop_requested, lookup_count, error, finished_at) values
  ('dddddddd-0000-4000-8000-0000000000f1', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'failed',
   '{dddddddd-0000-4000-8000-0000000000a1,dddddddd-0000-4000-8000-0000000000a2,dddddddd-0000-4000-8000-0000000000a3}',
   '{"limit": 200}', 'k1', 'dddddddd-0000-4000-8000-0000000000c1', 0, false, 5, 'worker_offline', now()),
  ('dddddddd-0000-4000-8000-0000000000f2', 'dddddddd-0000-4000-8000-000000000002', 'collect', 'failed',
   '{}', '{}', 'k2', null, 0, false, 0, null, null),
  ('dddddddd-0000-4000-8000-0000000000f3', 'dddddddd-0000-4000-8000-000000000001', 'verify', 'failed',
   '{}', '{}', 'k3', null, 0, false, 0, null, null),
  ('dddddddd-0000-4000-8000-0000000000f4', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'failed',
   '{dddddddd-0000-4000-8000-0000000000a1}', '{}', 'k4', null, 3, false, 0, null, null),
  ('dddddddd-0000-4000-8000-0000000000f5', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'failed',
   '{dddddddd-0000-4000-8000-0000000000a1}', '{}', 'k5', null, 0, true, 0, null, null),
  ('dddddddd-0000-4000-8000-0000000000f6', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'failed',
   '{dddddddd-0000-4000-8000-0000000000a1}', '{}', 'k6', null, 0, false, 200, null, null),
  ('dddddddd-0000-4000-8000-0000000000f7', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'failed',
   '{dddddddd-0000-4000-8000-0000000000a1}', '{"limit": 2}', 'k7', null, 0, false, 0, null, null),
  ('dddddddd-0000-4000-8000-0000000000f8', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'failed',
   '{dddddddd-0000-4000-8000-0000000000a1}', '{}', 'k8', null, 0, false, 0, null, null);
insert into public.job_profile_runs (workspace_id, job_id, profile_id, position, collected_count, status) values
  ('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1', 'dddddddd-0000-4000-8000-0000000000a1', 0, 3, 'done'),
  ('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1', 'dddddddd-0000-4000-8000-0000000000a2', 1, 2, 'failed'),
  ('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1', 'dddddddd-0000-4000-8000-0000000000a3', 2, 0, 'failed'),
  ('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f7', 'dddddddd-0000-4000-8000-0000000000a1', 0, 2, 'failed'),
  ('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f8', 'dddddddd-0000-4000-8000-0000000000a1', 0, 1, 'done');

-- 1. 함수 속성·권한
select is(
  (select proconfig from pg_proc where oid = 'public.retry_collect_job(uuid, uuid)'::regprocedure),
  array['search_path=""'], 'retry search_path 비움');
select is(
  (select prosecdef from pg_proc where oid = 'public.retry_collect_job(uuid, uuid)'::regprocedure),
  false, 'retry security invoker');
select is(
  (select proconfig from pg_proc where oid = 'public.stop_collect_job(uuid, uuid)'::regprocedure),
  array['search_path=""'], 'stop search_path 비움');
select is(
  (select prosecdef from pg_proc where oid = 'public.stop_collect_job(uuid, uuid)'::regprocedure),
  false, 'stop security invoker');
select ok(not has_function_privilege('public', 'public.retry_collect_job(uuid, uuid)', 'execute'), 'retry public 실행 권한 없음');
select ok(not has_function_privilege('public', 'public.stop_collect_job(uuid, uuid)', 'execute'), 'stop public 실행 권한 없음');
set local role authenticated;
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1')$$,
  '42501', null, 'retry authenticated 거부');
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1')$$,
  '42501', null, 'stop authenticated 거부');
reset role;
set local role anon;
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1')$$,
  '42501', null, 'retry anon 거부');
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1')$$,
  '42501', null, 'stop anon 거부');
reset role;

set local role service_role;
-- 2. retry 거부 경로
select throws_ok(
  $$select public.retry_collect_job(null, 'dddddddd-0000-4000-8000-0000000000f1')$$, '22023', null, 'retry 잘못된 인자');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f2')$$,
  'NR003', null, 'retry 다른 워크스페이스 작업 거부');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f3')$$,
  'NR003', null, 'retry verify 작업 거부');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f4')$$,
  'NR006', null, 'retry 상한 3회 거부');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f5')$$,
  'NR006', null, 'retry 중지 요청된 작업 거부');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f6')$$,
  'NR005', null, 'retry 조회 상한(lookup_count) 거부');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f7')$$,
  'NR005', null, 'retry 수집 수 상한 거부');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f8')$$,
  'NR006', null, 'retry 남은 프로필 없음 거부');

-- params.limit이 문자열이면 기본 200으로 본다(형 변환 오류 없이 NR005 판정까지 진행)
reset role;
update public.jobs set params = '{"limit": "abc"}' where id = 'dddddddd-0000-4000-8000-0000000000f6';
set local role service_role;
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f6')$$,
  'NR005', null, 'retry 문자열 limit은 기본 200(lookup 200 → 상한)');

-- 3. retry 성공: f1 → retrying, p2부터
select is(
  public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1') ->> 'status',
  'retrying', 'retry 성공');
select results_eq(
  $$select status, retry_count, error, finished_at, claimed_by, lookup_count,
           params ->> 'resume_from_profile_id', (params ->> 'limit')::integer
      from public.jobs where id = 'dddddddd-0000-4000-8000-0000000000f1'$$,
  $$values ('retrying'::text, 1, null::text, null::timestamptz, null::uuid, 5,
            'dddddddd-0000-4000-8000-0000000000a2'::text, 200)$$,
  'retry: 상태·횟수·초기화·lookup_count 유지·resume·limit 보존');
select results_eq(
  $$select status from public.job_profile_runs
     where job_id = 'dddddddd-0000-4000-8000-0000000000f1' order by position$$,
  $$values ('done'::text), ('pending'::text), ('pending'::text)$$,
  'retry: done 유지·이후 failed 행은 pending');
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1')$$,
  'NR006', null, '두 번째 retry(retrying) 거부');
-- f1이 활성(retrying)이라 다른 failed job retry는 NR007
update public.job_profile_runs set status = 'failed' where job_id = 'dddddddd-0000-4000-8000-0000000000f8';
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f8')$$,
  'NR007', null, '다른 활성 수집 작업이 있으면 거부');

-- 4. stop
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f2')$$,
  'NR003', null, 'stop 다른 워크스페이스 거부');
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f3')$$,
  'NR003', null, 'stop verify 작업 거부');
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f4')$$,
  'NR006', null, 'stop failed 작업 거부');
-- retrying → 즉시 stopped
select is(
  public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1'),
  jsonb_build_object('id', 'dddddddd-0000-4000-8000-0000000000f1'::uuid, 'status', 'stopped',
                     'stop_requested', false, 'retry_count', 1),
  'retrying → stopped');
select results_eq(
  $$select error, finished_at is not null from public.jobs where id = 'dddddddd-0000-4000-8000-0000000000f1'$$,
  $$values ('stopped_by_user'::text, true)$$, 'stopped: error·finished_at');
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1')$$,
  'NR006', null, 'stopped 다시 stop 거부');
-- queued → 즉시 stopped
reset role;
insert into public.jobs (id, workspace_id, kind, status, profile_ids, idempotency_key) values
  ('dddddddd-0000-4000-8000-0000000000e1', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'queued',
   '{dddddddd-0000-4000-8000-0000000000a1}', 'q1');
set local role service_role;
select is(
  public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000e1') ->> 'status',
  'stopped', 'queued → stopped');
-- running → stop_requested만
reset role;
insert into public.jobs (id, workspace_id, kind, status, profile_ids, idempotency_key, claimed_by) values
  ('dddddddd-0000-4000-8000-0000000000e2', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'running',
   '{dddddddd-0000-4000-8000-0000000000a1}', 'r1', 'dddddddd-0000-4000-8000-0000000000c1');
set local role service_role;
select is(
  public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000e2'),
  jsonb_build_object('id', 'dddddddd-0000-4000-8000-0000000000e2'::uuid, 'status', 'running',
                     'stop_requested', true, 'retry_count', 0),
  'running → stop_requested');
select results_eq(
  $$select status, error, finished_at from public.jobs where id = 'dddddddd-0000-4000-8000-0000000000e2'$$,
  $$values ('running'::text, null::text, null::timestamptz)$$, 'running은 상태 유지');
select is(
  public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000e2') ->> 'stop_requested',
  'true', 'running 다시 stop은 멱등');
-- 중지 요청 뒤 실패한 job은 retry 불가(◆2)
reset role;
update public.jobs set status = 'failed', error = 'worker_offline'
  where id = 'dddddddd-0000-4000-8000-0000000000e2';
set local role service_role;
select throws_ok(
  $$select public.retry_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000e2')$$,
  'NR006', null, '중지 요청 뒤 실패한 작업 retry 거부');
reset role;
update public.jobs set status = 'done', error = null where id = 'dddddddd-0000-4000-8000-0000000000e2';
set local role service_role;
select throws_ok(
  $$select public.stop_collect_job('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000e2')$$,
  'NR006', null, 'done 작업 stop 거부');
select throws_ok(
  $$select public.stop_collect_job(null, null)$$, '22023', null, 'stop 잘못된 인자');
reset role;

select * from finish();
rollback;
