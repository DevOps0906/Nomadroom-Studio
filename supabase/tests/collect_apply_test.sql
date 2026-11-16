-- task-007 apply_collect_batch RPC 테스트 (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(27);

insert into public.workspaces (id, name) values
  ('dddddddd-0000-4000-8000-000000000001', 'collect-ws'),
  ('dddddddd-0000-4000-8000-000000000002', 'collect-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('dddddddd-0000-4000-8000-0000000000a1', 'dddddddd-0000-4000-8000-000000000001', 'p1', 'KR', 5),
  ('dddddddd-0000-4000-8000-0000000000a2', 'dddddddd-0000-4000-8000-000000000001', 'p2', 'JP', 5),
  ('dddddddd-0000-4000-8000-0000000000a3', 'dddddddd-0000-4000-8000-000000000001', 'p3', 'KR', 5),
  ('dddddddd-0000-4000-8000-0000000000b1', 'dddddddd-0000-4000-8000-000000000002', 'o1', 'KR', 5);
insert into public.workers (id, workspace_id, name, token_hash) values
  ('dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-000000000001', 'w1', 'x'),
  ('dddddddd-0000-4000-8000-0000000000c2', 'dddddddd-0000-4000-8000-000000000001', 'w2', 'x'),
  ('dddddddd-0000-4000-8000-0000000000c3', 'dddddddd-0000-4000-8000-000000000002', 'w3', 'x');
insert into public.jobs (id, workspace_id, kind, status, profile_ids, idempotency_key, claimed_by) values
  ('dddddddd-0000-4000-8000-0000000000f1', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'running',
   '{dddddddd-0000-4000-8000-0000000000a1,dddddddd-0000-4000-8000-0000000000a2}', 'k1',
   'dddddddd-0000-4000-8000-0000000000c1'),
  ('dddddddd-0000-4000-8000-0000000000f2', 'dddddddd-0000-4000-8000-000000000002', 'collect', 'running',
   '{dddddddd-0000-4000-8000-0000000000b1}', 'k2', 'dddddddd-0000-4000-8000-0000000000c3'),
  ('dddddddd-0000-4000-8000-0000000000f3', 'dddddddd-0000-4000-8000-000000000001', 'collect', 'done',
   '{dddddddd-0000-4000-8000-0000000000a1}', 'k3', 'dddddddd-0000-4000-8000-0000000000c1'),
  ('dddddddd-0000-4000-8000-0000000000f4', 'dddddddd-0000-4000-8000-000000000001', 'verify', 'running',
   '{dddddddd-0000-4000-8000-0000000000a1}', 'k4', null);
-- 이미 있는 후보(다른 프로필이 먼저 넣은 것)
insert into public.candidates (id, workspace_id, video_id, title, market) values
  ('dddddddd-0000-4000-8000-0000000000e1', 'dddddddd-0000-4000-8000-000000000001', 'existVid001', '기존', 'KR');

create function pg_temp.item(p_vid text, p_status text default 'pending', p_reason text default 'no_prev')
returns jsonb language sql as $$
  select jsonb_build_object(
    'video_id', p_vid, 'title', 'yt ' || p_vid,
    'thumbnail_url', 'https://i.ytimg.com/vi/' || p_vid || '/hqdefault.jpg',
    'genre', '음악', 'category', null, 'format', 'long', 'market', 'KR',
    'channel_id', 'UCxxxxxxxxxxxxxxxxxxxxxx', 'channel_title', '채널',
    'license_cc', true, 'is_broadcaster', false,
    'observed_at', '2026-11-17T00:00:00Z', 'view_count', 1234,
    'status', p_status, 'reason', p_reason);
$$;
grant execute on function pg_temp.item(text, text, text) to service_role;

-- 1. 함수 속성
select is(
  (select prosecdef from pg_proc
    where oid = 'public.apply_collect_batch(uuid, uuid, uuid, uuid, jsonb)'::regprocedure),
  false, 'apply_collect_batch security invoker');
select is(
  (select proconfig from pg_proc
    where oid = 'public.apply_collect_batch(uuid, uuid, uuid, uuid, jsonb)'::regprocedure),
  array['search_path=""'], 'apply_collect_batch search_path 비움');
select ok(
  has_function_privilege('service_role', 'public.apply_collect_batch(uuid, uuid, uuid, uuid, jsonb)', 'execute'),
  'service_role 실행 가능');

-- 2. 브라우저 역할 거부
set local role authenticated;
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  '42501', null, 'authenticated 거부');
reset role;
set local role anon;
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  '42501', null, 'anon 거부');
reset role;

set local role service_role;

-- 3. 거부 경로
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f2',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  'NR003', null, '다른 워크스페이스 작업 거부');
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f4',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  'NR003', null, 'verify 작업 거부');
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c2', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  'NR004', null, '다른 워커 거부');
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f3',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  'NR004', null, '종료된 작업 거부');
select throws_ok(
  $$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a3', '{}')$$,
  'NR003', null, '작업에 속하지 않은 프로필 거부');
select throws_ok(
  $$select public.apply_collect_batch(null, 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{}')$$,
  '22023', null, 'null 인자 거부');

-- 4. 원자성: 둘째 항목 판정 상태가 잘못되면 첫 항목도 들어가지 않는다
select throws_ok(
  format($$select public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a2', %L)$$,
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('atomVid0001'), pg_temp.item('atomVid0002', 'bogus', null)))),
  '23514', null, '잘못된 항목이 있으면 실패');
select is((select count(*)::int from public.candidates where video_id like 'atomVid%'), 0, '원자성: 후보 0건');
select is((select count(*)::int from public.job_profile_runs
  where job_id = 'dddddddd-0000-4000-8000-0000000000f1'), 0, '원자성: 진행 행 없음');

-- 5. 정상 반영: 새 후보 2건 + 기존 후보 1건(건너뜀)
select is(
  public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a2',
    jsonb_build_object('items', jsonb_build_array(
      pg_temp.item('newVid00001'), pg_temp.item('newVid00002', 'excluded', 'market'), pg_temp.item('existVid001')))),
  2, '새 후보 2건 반영');
select is(
  (select row(c.title, c.first_job_id, c.rep_status, c.rep_profile_id, c.license_cc)::text
     from public.candidates c where c.video_id = 'newVid00001'),
  row('yt newVid00001', 'dddddddd-0000-4000-8000-0000000000f1'::uuid, 'pending',
      'dddddddd-0000-4000-8000-0000000000a2'::uuid, true)::text,
  '후보 값·first_job_id·대표 판정');
select is(
  (select c.rep_status from public.candidates c where c.video_id = 'newVid00002'), 'excluded', '대표 판정 = 프로필 판정');
select is(
  (select count(*)::int from public.observations o join public.candidates c on c.id = o.candidate_id
    where c.video_id like 'newVid%' and o.job_id = 'dddddddd-0000-4000-8000-0000000000f1' and o.view_count = 1234),
  2, '1차 관측 2건');
select is(
  (select count(*)::int from public.candidate_verdicts v join public.candidates c on c.id = v.candidate_id
    where c.video_id like 'newVid%' and v.curr_observation_id is not null and v.prev_observation_id is null),
  2, '판정 2건(이전 관측 없음)');
select is(
  (select count(*)::int from public.candidate_verdicts
    where candidate_id = 'dddddddd-0000-4000-8000-0000000000e1'), 0, '기존 후보에는 판정을 만들지 않음');
select is(
  (select title from public.candidates where id = 'dddddddd-0000-4000-8000-0000000000e1'), '기존', '기존 후보 그대로');
select is(
  (select row(position, collected_count, status)::text from public.job_profile_runs
    where job_id = 'dddddddd-0000-4000-8000-0000000000f1' and profile_id = 'dddddddd-0000-4000-8000-0000000000a2'),
  row(1, 2, 'running')::text, '진행 행 생성(position = profile_ids 순서)');

-- 6. collected_count 누적
select is(
  public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a2',
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('newVid00003'), pg_temp.item('newVid00001')))),
  1, '둘째 묶음 1건(중복 1건 건너뜀)');
select is(
  (select collected_count from public.job_profile_runs
    where job_id = 'dddddddd-0000-4000-8000-0000000000f1' and profile_id = 'dddddddd-0000-4000-8000-0000000000a2'),
  3, 'collected_count 원자적 증가');
select is(
  public.apply_collect_batch('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000f1',
    'dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-0000000000a1', '{"items": []}'),
  0, '빈 묶음 0건');
select is(
  (select row(position, collected_count)::text from public.job_profile_runs
    where job_id = 'dddddddd-0000-4000-8000-0000000000f1' and profile_id = 'dddddddd-0000-4000-8000-0000000000a1'),
  row(0, 0)::text, '첫 프로필 position 0');
reset role;

-- 7. 다른 워크스페이스 데이터 무변경
select is((select count(*)::int from public.candidates where workspace_id = 'dddddddd-0000-4000-8000-000000000002'),
  0, '다른 워크스페이스 후보 없음');

select * from finish();
rollback;
