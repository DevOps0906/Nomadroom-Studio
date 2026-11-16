-- task-007 리뷰 반영: reserve_collect_lookup·apply_collect_batch 상한·중지 요청·프로필 진행·DB 제약 (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(31);

insert into public.workspaces (id, name) values
  ('eeeeeeee-0000-4000-8000-000000000001', 'limits-ws'),
  ('eeeeeeee-0000-4000-8000-000000000002', 'limits-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('eeeeeeee-0000-4000-8000-0000000000a1', 'eeeeeeee-0000-4000-8000-000000000001', 'p1', 'KR', 5),
  ('eeeeeeee-0000-4000-8000-0000000000a2', 'eeeeeeee-0000-4000-8000-000000000001', 'p2', 'KR', 5),
  ('eeeeeeee-0000-4000-8000-0000000000a3', 'eeeeeeee-0000-4000-8000-000000000001', 'p3', 'KR', 5);
insert into public.workers (id, workspace_id, name, token_hash) values
  ('eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-000000000001', 'w1', 'x'),
  ('eeeeeeee-0000-4000-8000-0000000000c2', 'eeeeeeee-0000-4000-8000-000000000001', 'w2', 'x');
-- f1: limit 3, f2(다른 ws): running, f3: 중지 요청
insert into public.jobs (id, workspace_id, kind, status, profile_ids, params, idempotency_key, claimed_by, stop_requested) values
  ('eeeeeeee-0000-4000-8000-0000000000f1', 'eeeeeeee-0000-4000-8000-000000000001', 'collect', 'running',
   '{eeeeeeee-0000-4000-8000-0000000000a1,eeeeeeee-0000-4000-8000-0000000000a2,eeeeeeee-0000-4000-8000-0000000000a3}',
   '{"limit": 3}', 'k1', 'eeeeeeee-0000-4000-8000-0000000000c1', false),
  ('eeeeeeee-0000-4000-8000-0000000000f2', 'eeeeeeee-0000-4000-8000-000000000002', 'collect', 'running',
   '{}', '{}', 'k2', null, false),
  ('eeeeeeee-0000-4000-8000-0000000000f3', 'eeeeeeee-0000-4000-8000-000000000001', 'verify', 'running',
   '{eeeeeeee-0000-4000-8000-0000000000a1}', '{}', 'k3', 'eeeeeeee-0000-4000-8000-0000000000c2', true);

create function pg_temp.items(variadic p_vids text[])
returns jsonb language sql as $$
  select jsonb_build_object('items', coalesce(jsonb_agg(jsonb_build_object(
    'video_id', v, 'title', 't', 'market', 'KR', 'format', 'long', 'license_cc', true,
    'is_broadcaster', false, 'observed_at', '2026-11-17T00:00:00Z', 'view_count', 10,
    'status', 'pending', 'reason', 'no_prev')), '[]'::jsonb))
  from unnest(p_vids) as v;
$$;
grant execute on function pg_temp.items(text[]) to service_role;

-- 1. 함수 속성·권한
select is(
  (select proconfig from pg_proc
    where oid = 'public.reserve_collect_lookup(uuid, uuid, uuid, integer)'::regprocedure),
  array['search_path=""'], 'reserve_collect_lookup search_path 비움');
select is(
  (select prosecdef from pg_proc
    where oid = 'public.reserve_collect_lookup(uuid, uuid, uuid, integer)'::regprocedure),
  false, 'reserve_collect_lookup security invoker');
set local role authenticated;
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 1)$$, '42501', null, 'authenticated 거부');
reset role;
set local role anon;
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 1)$$, '42501', null, 'anon 거부');
reset role;

set local role service_role;
-- 2. reserve_collect_lookup 거부 경로
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f2',
    'eeeeeeee-0000-4000-8000-0000000000c1', 1)$$, 'NR003', null, '다른 워크스페이스 작업 거부');
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f3',
    'eeeeeeee-0000-4000-8000-0000000000c2', 1)$$, 'NR003', null, 'verify 작업 거부');
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c2', 1)$$, 'NR004', null, '다른 워커 거부');
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 0)$$, '22023', null, '0건 예약 거부');

-- 3. 누적 상한(limit 3)
select is(public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
  'eeeeeeee-0000-4000-8000-0000000000c1', 2), 2, '2건 예약');
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 2)$$, 'NR005', null, '누적 상한 초과 거부');
select is((select lookup_count from public.jobs where id = 'eeeeeeee-0000-4000-8000-0000000000f1'), 2, '거부 시 누적 불변');
select is(public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
  'eeeeeeee-0000-4000-8000-0000000000c1', 1), 3, '상한까지 예약');

-- 4. apply_collect_batch: 프로필 진행·누적 상한
select is(public.apply_collect_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
  'eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-0000000000a1', pg_temp.items('limVid00001')),
  1, '프로필 1 후보 1건');
select is(public.apply_collect_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
  'eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-0000000000a2', pg_temp.items('limVid00002')),
  1, '프로필 2 후보 1건');
select is(
  (select array_agg(status order by position) from public.job_profile_runs
    where job_id = 'eeeeeeee-0000-4000-8000-0000000000f1'),
  array['done', 'running'], '다음 프로필 후보가 오면 앞 프로필 running → done');
select throws_ok(
  format($$select public.apply_collect_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-0000000000a3', %L)$$,
    pg_temp.items('limVid00003', 'limVid00004')),
  'NR005', null, '누적 accepted + 신규 > limit 거부');
select is((select count(*)::int from public.candidates where video_id in ('limVid00003', 'limVid00004')),
  0, '상한 초과 묶음은 롤백');
select is(
  (select array_agg(status order by position) from public.job_profile_runs
    where job_id = 'eeeeeeee-0000-4000-8000-0000000000f1'),
  array['done', 'running'], '롤백 시 프로필 진행 불변');
select is(public.apply_collect_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
  'eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-0000000000a3', pg_temp.items('limVid00003')),
  1, '상한까지는 반영');
select is(
  (select array_agg(status order by position) from public.job_profile_runs
    where job_id = 'eeeeeeee-0000-4000-8000-0000000000f1'),
  array['done', 'done', 'running'], '프로필 3 진행 시 앞 프로필 done');

-- 5. 중지 요청된 job은 예약·반영 모두 거부
reset role;
update public.jobs set stop_requested = true, params = '{}' where id = 'eeeeeeee-0000-4000-8000-0000000000f1';
set local role service_role;
select throws_ok(
  $$select public.reserve_collect_lookup('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 1)$$, 'NR004', null, '중지 요청 job 예약 거부');
select throws_ok(
  format($$select public.apply_collect_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-0000000000a3', %L)$$, pg_temp.items('limVid00009')),
  'NR004', null, '중지 요청 job 반영 거부');
reset role;

-- 6. 활성 collect job은 워크스페이스당 1건(queued·retrying 공존 불가)
insert into public.jobs (workspace_id, kind, status, idempotency_key) values
  ('eeeeeeee-0000-4000-8000-000000000002', 'collect', 'stopped', 'k-old');
update public.jobs set status = 'failed' where id = 'eeeeeeee-0000-4000-8000-0000000000f2';
insert into public.jobs (workspace_id, kind, status, idempotency_key) values
  ('eeeeeeee-0000-4000-8000-000000000002', 'collect', 'queued', 'k-q');
select throws_ok(
  $$insert into public.jobs (workspace_id, kind, status, idempotency_key)
    values ('eeeeeeee-0000-4000-8000-000000000002', 'collect', 'retrying', 'k-r')$$,
  '23505', null, 'queued와 retrying 공존 불가');
select throws_ok(
  $$update public.jobs set status = 'retrying' where id = 'eeeeeeee-0000-4000-8000-0000000000f2'$$,
  '23505', null, 'queued가 있으면 failed → retrying 불가');

-- 7. DB 방어선 제약
select throws_ok(
  $$update public.jobs set error = 'C:\Users\x cookie' where id = 'eeeeeeee-0000-4000-8000-0000000000f2'$$,
  '23514', null, 'jobs.error 코드 외 거부');
select lives_ok(
  $$update public.jobs set error = 'worker_offline' where id = 'eeeeeeee-0000-4000-8000-0000000000f2'$$,
  'jobs.error 코드 허용');
select throws_ok(
  $$update public.job_profile_runs set detail = 'SID=abc' where job_id = 'eeeeeeee-0000-4000-8000-0000000000f1'$$,
  '23514', null, 'job_profile_runs.detail 코드 외 거부');
select lives_ok(
  $$update public.job_profile_runs set detail = 'login_required' where job_id = 'eeeeeeee-0000-4000-8000-0000000000f1'$$,
  'job_profile_runs.detail 코드 허용');
select throws_ok(
  $$insert into public.candidates (workspace_id, video_id, title, market)
    values ('eeeeeeee-0000-4000-8000-000000000001', 'mktVid00001', 't', 'US')$$,
  '23514', null, 'candidates.market KR·JP 외 거부');
select throws_ok(
  $$insert into public.candidates (workspace_id, video_id, title, market, format)
    values ('eeeeeeee-0000-4000-8000-000000000001', 'fmtVid00001', 't', 'KR', 'medium')$$,
  '23514', null, 'candidates.format short·long 외 거부');
select is(
  (select count(*)::int from public.candidates where market is not null and market not in ('KR', 'JP')),
  0, '기존 행 충돌 없음');

select * from finish();
rollback;
