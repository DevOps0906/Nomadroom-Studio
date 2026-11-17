-- task-019: 검색 할당량 예약 경계·원자성, 검색 job 수령 배제, retry·stop 거부, apply_search_batch (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(40);

insert into public.workspaces (id, name) values
  ('eeeeeeee-0000-4000-8000-000000000001', 'search-ws'),
  ('eeeeeeee-0000-4000-8000-000000000002', 'search-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('eeeeeeee-0000-4000-8000-0000000000a1', 'eeeeeeee-0000-4000-8000-000000000001', 'p1', 'KR', 5),
  ('eeeeeeee-0000-4000-8000-0000000000a2', 'eeeeeeee-0000-4000-8000-000000000001', 'p2', 'KR', 5),
  ('eeeeeeee-0000-4000-8000-0000000000a3', 'eeeeeeee-0000-4000-8000-000000000001', 'p3', 'KR', 5);
insert into public.workers (id, workspace_id, name, token_hash) values
  ('eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-000000000001', 'w1', 'x');

-- s1: running 검색 job(p1·p2), s2: failed 검색 job, s3: done 검색 job, v1: vidIQ failed job
insert into public.jobs (id, workspace_id, kind, status, profile_ids, params, idempotency_key, started_at) values
  ('eeeeeeee-0000-4000-8000-0000000000f1', 'eeeeeeee-0000-4000-8000-000000000001', 'collect', 'running',
   '{eeeeeeee-0000-4000-8000-0000000000a1,eeeeeeee-0000-4000-8000-0000000000a2}',
   '{"limit": 200, "source": "youtube_search"}', 's1', now()),
  ('eeeeeeee-0000-4000-8000-0000000000f2', 'eeeeeeee-0000-4000-8000-000000000001', 'collect', 'failed',
   '{eeeeeeee-0000-4000-8000-0000000000a1}', '{"limit": 200, "source": "youtube_search"}', 's2', now()),
  ('eeeeeeee-0000-4000-8000-0000000000f3', 'eeeeeeee-0000-4000-8000-000000000001', 'collect', 'done',
   '{eeeeeeee-0000-4000-8000-0000000000a1}', '{"limit": 200, "source": "youtube_search"}', 's3', now()),
  ('eeeeeeee-0000-4000-8000-0000000000f4', 'eeeeeeee-0000-4000-8000-000000000002', 'collect', 'failed',
   '{}', '{"limit": 200}', 'v1', null);
insert into public.candidates (id, workspace_id, video_id, title, market) values
  ('eeeeeeee-0000-4000-8000-0000000000e1', 'eeeeeeee-0000-4000-8000-000000000001', 'existVid001', '기존', 'KR');

create function pg_temp.item(p_vid text, p_vprofile uuid default 'eeeeeeee-0000-4000-8000-0000000000a2')
returns jsonb language sql as $$
  select jsonb_build_object(
    'video_id', p_vid, 'title', 'yt ' || p_vid,
    'thumbnail_url', 'https://i.ytimg.com/vi/' || p_vid || '/hqdefault.jpg',
    'category', null, 'format', 'short', 'market', 'KR',
    'channel_id', 'UCxxxxxxxxxxxxxxxxxxxxxx', 'channel_title', '채널',
    'license_cc', false, 'is_broadcaster', false,
    'observed_at', '2026-11-18T00:00:00Z', 'view_count', 500,
    'rep_status', 'pending', 'rep_profile_id', 'eeeeeeee-0000-4000-8000-0000000000a2',
    'verdicts', jsonb_build_array(
      jsonb_build_object('profile_id', 'eeeeeeee-0000-4000-8000-0000000000a1',
                         'status', 'excluded', 'reason', 'views_min'),
      jsonb_build_object('profile_id', p_vprofile, 'status', 'pending', 'reason', 'no_prev')));
$$;

grant execute on function pg_temp.item(text, uuid) to service_role;

-- 1. 함수 속성·권한 -------------------------------------------------------------
select is((select proconfig from pg_proc where oid = 'public.reserve_search_quota(integer, integer, integer)'::regprocedure),
  array['search_path=""'], 'reserve_search_quota search_path 비움');
select is((select prosecdef from pg_proc where oid = 'public.reserve_search_quota(integer, integer, integer)'::regprocedure),
  false, 'reserve_search_quota security invoker');
select is((select proconfig from pg_proc where oid = 'public.apply_search_batch(uuid, uuid, uuid, jsonb)'::regprocedure),
  array['search_path=""'], 'apply_search_batch search_path 비움');
select is((select prosecdef from pg_proc where oid = 'public.apply_search_batch(uuid, uuid, uuid, jsonb)'::regprocedure),
  false, 'apply_search_batch security invoker');
select ok(not has_function_privilege('public', 'public.reserve_search_quota(integer, integer, integer)', 'execute'),
  'reserve_search_quota public 실행 권한 없음');
select ok(not has_function_privilege('public', 'public.apply_search_batch(uuid, uuid, uuid, jsonb)', 'execute'),
  'apply_search_batch public 실행 권한 없음');
set local role authenticated;
select throws_ok($$select public.reserve_search_quota(100, 2000, 8000)$$, '42501', null, 'reserve authenticated 거부');
select throws_ok(
  $$select public.apply_search_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000a1', '{}')$$, '42501', null, 'apply authenticated 거부');
reset role;
set local role anon;
select throws_ok($$select public.reserve_search_quota(100, 2000, 8000)$$, '42501', null, 'reserve anon 거부');
reset role;

-- 2. 예약 경계(오늘 행을 비우고 시작, 트랜잭션이라 롤백된다) ------------------------------
delete from public.api_quota_daily where day = public.quota_day(now());
set local role service_role;
select throws_ok($$select public.reserve_search_quota(0, 2000, 8000)$$, '22023', null, '0 unit 거부');
select throws_ok($$select public.reserve_search_quota(100, null, 8000)$$, '22023', null, 'null 상한 거부');
select is(public.reserve_search_quota(2100, 2000, 8000), false, '첫 예약도 검색 상한 초과면 false');
select is((select count(*)::int from public.api_quota_daily where day = public.quota_day(now())), 0,
  '실패한 첫 예약은 행을 만들지 않음');
select is(public.reserve_search_quota(1900, 2000, 8000), true, '1,900 예약');
select is(public.reserve_search_quota(100, 2000, 8000), true, '검색 상한 2,000 정확히 도달 허용');
select is(public.reserve_search_quota(100, 2000, 8000), false, '검색 상한 초과 거부');
select is((select (units, search_units)::text from public.api_quota_daily where day = public.quota_day(now())),
  '(2000,2000)', '거부 시 두 카운터 모두 그대로');
-- 전체 방어선: 검색 상한 여유가 있어도 units가 넘치면 거부(부분 갱신 없음)
update public.api_quota_daily set units = 7950, search_units = 0 where day = public.quota_day(now());
select is(public.reserve_search_quota(100, 2000, 8000), false, '전체 방어선 8,000 초과 거부');
select is((select (units, search_units)::text from public.api_quota_daily where day = public.quota_day(now())),
  '(7950,0)', '방어선 거부 시 search_units도 그대로(원자적)');
update public.api_quota_daily set units = 7900 where day = public.quota_day(now());
select is(public.reserve_search_quota(100, 2000, 8000), true, '전체 방어선 8,000 정확히 도달 허용');
select is(public.reserve_quota(1, 8000), false, '방어선 도달 후 videos.list 예약도 거부');
update public.api_quota_daily set units = 9950, search_units = 0 where day = public.quota_day(now());
select is(public.reserve_search_quota(100, 50000, 50000), false, '절대 상한 10,000 초과 거부');
reset role;

-- 3. 검색 job 수령 배제(DB 제약) ---------------------------------------------------
select throws_ok(
  $$update public.jobs set claimed_by = 'eeeeeeee-0000-4000-8000-0000000000c1'
    where id = 'eeeeeeee-0000-4000-8000-0000000000f1'$$,
  '23514', null, '검색 job에 claimed_by 설정 불가');
select throws_ok(
  $$insert into public.jobs (workspace_id, kind, status, profile_ids, params, idempotency_key)
    values ('eeeeeeee-0000-4000-8000-000000000002', 'collect', 'queued', '{}',
            '{"source": "youtube_search"}', 'q1')$$,
  '23514', null, '검색 job은 queued로 만들 수 없음');
select throws_ok(
  $$update public.jobs set status = 'retrying' where id = 'eeeeeeee-0000-4000-8000-0000000000f2'$$,
  '23514', null, '검색 job은 retrying이 될 수 없음');
-- W-01 claim 조건(API 필터와 같은 식)으로는 검색 job이 잡히지 않는다
select is((select count(*)::int from public.jobs j
  where j.workspace_id = 'eeeeeeee-0000-4000-8000-000000000001' and j.kind = 'collect'
    and j.status in ('queued', 'retrying')
    and (j.params ->> 'source' is null or j.params ->> 'source' <> 'youtube_search')), 0,
  'claim 필터에 검색 job 없음');

-- 4. retry·stop RPC는 검색 job 거부 -------------------------------------------------
set local role service_role;
select throws_ok(
  $$select public.retry_collect_job('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f2')$$,
  'NR008', null, 'retry RPC 검색 job 거부');
select throws_ok(
  $$select public.stop_collect_job('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1')$$,
  'NR008', null, 'stop RPC 검색 job 거부');
select is((select (status, stop_requested, retry_count)::text from public.jobs
  where id = 'eeeeeeee-0000-4000-8000-0000000000f1'), '(running,f,0)', '거부 후 job 그대로');
select throws_ok(
  $$select public.retry_collect_job('eeeeeeee-0000-4000-8000-000000000002', 'eeeeeeee-0000-4000-8000-0000000000f4')$$,
  'NR006', null, 'vidIQ job은 기존 규칙(남은 프로필 없음 NR006)');

-- 5. apply_search_batch -----------------------------------------------------------
select throws_ok(
  $$select public.apply_search_batch('eeeeeeee-0000-4000-8000-000000000002', 'eeeeeeee-0000-4000-8000-0000000000f4',
    'eeeeeeee-0000-4000-8000-0000000000a1', '{}')$$, 'NR003', null, 'vidIQ job 거부');
select throws_ok(
  $$select public.apply_search_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f3',
    'eeeeeeee-0000-4000-8000-0000000000a1', '{}')$$, 'NR004', null, '종료된 검색 job 거부');
select throws_ok(
  $$select public.apply_search_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000a3', '{}')$$, 'NR003', null, '작업에 속하지 않은 프로필 거부');
select throws_ok(
  format($$select public.apply_search_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000a1', %L)$$,
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('atomVid0001'),
      pg_temp.item('atomVid0002', 'eeeeeeee-0000-4000-8000-0000000000a3')))),
  'NR003', null, '작업 밖 프로필 판정이 있으면 전체 실패');
select is((select count(*)::int from public.candidates where video_id like 'atomVid%'), 0, '원자성: 후보 0건');

select is(
  public.apply_search_batch('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-0000000000f1',
    'eeeeeeee-0000-4000-8000-0000000000a1',
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('newVid00001'), pg_temp.item('existVid001')))),
  1, '새 후보 1건 반영(기존 후보 건너뜀)');
select is((select count(*)::int from public.candidate_verdicts v join public.candidates c on c.id = v.candidate_id
  where c.video_id = 'newVid00001'), 2, '이번 실행 프로필 2개 모두 판정');
select is((select (rep_status, rep_profile_id, first_job_id, format)::text from public.candidates where video_id = 'newVid00001'),
  '(pending,eeeeeeee-0000-4000-8000-0000000000a2,eeeeeeee-0000-4000-8000-0000000000f1,short)', '대표 판정·first_job_id·형식');
select is((select count(*)::int from public.candidate_verdicts where candidate_id = 'eeeeeeee-0000-4000-8000-0000000000e1'),
  0, '기존 후보에는 판정을 만들지 않음');
select is((select (status, collected_count, position)::text from public.job_profile_runs
  where job_id = 'eeeeeeee-0000-4000-8000-0000000000f1' and profile_id = 'eeeeeeee-0000-4000-8000-0000000000a1'),
  '(done,1,0)', '실행 행 done·수집 수');
reset role;

select * from finish();
rollback;
