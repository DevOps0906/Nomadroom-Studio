-- task-019 리뷰 반영: apply_search_batch 소속 검사 범위·release_search_quota (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(14);

insert into public.workspaces (id, name) values
  ('ffffffff-0000-4000-8000-000000000001', 'fix-ws'),
  ('ffffffff-0000-4000-8000-000000000002', 'fix-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('ffffffff-0000-4000-8000-0000000000a1', 'ffffffff-0000-4000-8000-000000000001', 'p1', 'KR', 5),
  ('ffffffff-0000-4000-8000-0000000000b1', 'ffffffff-0000-4000-8000-000000000002', 'o1', 'KR', 5);
-- profile_ids에 삭제된 프로필(a9, profiles에 없음)과 다른 워크스페이스 프로필(b1)이 남은 running 검색 job
insert into public.jobs (id, workspace_id, kind, status, profile_ids, params, idempotency_key, started_at) values
  ('ffffffff-0000-4000-8000-0000000000f1', 'ffffffff-0000-4000-8000-000000000001', 'collect', 'running',
   '{ffffffff-0000-4000-8000-0000000000a1,ffffffff-0000-4000-8000-0000000000a9,ffffffff-0000-4000-8000-0000000000b1}',
   '{"limit": 200, "source": "youtube_search"}', 'f1', now());

create function pg_temp.item(p_vid text, p_vprofile uuid, p_rep uuid)
returns jsonb language sql as $$
  select jsonb_build_object(
    'video_id', p_vid, 'title', 'yt ' || p_vid,
    'thumbnail_url', 'https://i.ytimg.com/vi/' || p_vid || '/hqdefault.jpg',
    'category', null, 'format', 'long', 'market', 'KR',
    'channel_id', null, 'channel_title', null, 'license_cc', false, 'is_broadcaster', false,
    'observed_at', '2026-11-18T00:00:00Z', 'view_count', 10,
    'rep_status', 'pending', 'rep_profile_id', p_rep,
    'verdicts', jsonb_build_array(
      jsonb_build_object('profile_id', p_vprofile, 'status', 'pending', 'reason', 'no_prev')));
$$;
grant execute on function pg_temp.item(text, uuid, uuid) to service_role;

-- 1. 소속 검사 범위 ----------------------------------------------------------------
set local role service_role;
select is(
  public.apply_search_batch('ffffffff-0000-4000-8000-000000000001', 'ffffffff-0000-4000-8000-0000000000f1',
    'ffffffff-0000-4000-8000-0000000000a1',
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('fixVid00001',
      'ffffffff-0000-4000-8000-0000000000a1', 'ffffffff-0000-4000-8000-0000000000a1')))),
  1, '삭제된 프로필이 profile_ids에 남아도 쓰지 않으면 반영');
select throws_ok(
  $$select public.apply_search_batch('ffffffff-0000-4000-8000-000000000001', 'ffffffff-0000-4000-8000-0000000000f1',
    'ffffffff-0000-4000-8000-0000000000a9', '{}')$$,
  'NR003', null, '삭제된 프로필을 p_profile로 쓰면 거부');
select throws_ok(
  $$select public.apply_search_batch('ffffffff-0000-4000-8000-000000000001', 'ffffffff-0000-4000-8000-0000000000f1',
    'ffffffff-0000-4000-8000-0000000000b1', '{}')$$,
  'NR003', null, '다른 워크스페이스 프로필을 p_profile로 쓰면 거부');
select throws_ok(
  format($$select public.apply_search_batch('ffffffff-0000-4000-8000-000000000001', 'ffffffff-0000-4000-8000-0000000000f1',
    'ffffffff-0000-4000-8000-0000000000a1', %L)$$,
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('fixVid00002',
      'ffffffff-0000-4000-8000-0000000000b1', 'ffffffff-0000-4000-8000-0000000000a1')))),
  'NR003', null, '다른 워크스페이스 프로필 판정 거부');
select throws_ok(
  format($$select public.apply_search_batch('ffffffff-0000-4000-8000-000000000001', 'ffffffff-0000-4000-8000-0000000000f1',
    'ffffffff-0000-4000-8000-0000000000a1', %L)$$,
    jsonb_build_object('items', jsonb_build_array(pg_temp.item('fixVid00003',
      'ffffffff-0000-4000-8000-0000000000a1', 'ffffffff-0000-4000-8000-0000000000a9')))),
  'NR003', null, '삭제된 프로필을 대표로 쓰면 거부');
select is((select count(*)::int from public.candidates where video_id in ('fixVid00002', 'fixVid00003')),
  0, '거부된 호출은 후보를 남기지 않음');
reset role;

-- 2. release_search_quota ---------------------------------------------------------
select is((select proconfig from pg_proc where oid = 'public.release_search_quota(integer)'::regprocedure),
  array['search_path=""'], 'release search_path 비움');
select ok(not has_function_privilege('public', 'public.release_search_quota(integer)', 'execute'),
  'release public 실행 권한 없음');
set local role authenticated;
select throws_ok($$select public.release_search_quota(100)$$, '42501', null, 'release authenticated 거부');
reset role;

delete from public.api_quota_daily where day = public.quota_day(now());
set local role service_role;
select throws_ok($$select public.release_search_quota(0)$$, '22023', null, '0 unit 거부');
select lives_ok($$select public.release_search_quota(100)$$, '행이 없으면 아무것도 안 함');
select ok(public.reserve_search_quota(300, 2000, 8000), '300 예약');
select public.release_search_quota(200);
select is((select (units, search_units)::text from public.api_quota_daily where day = public.quota_day(now())),
  '(100,100)', '200 되돌림');
select public.release_search_quota(500);
select is((select (units, search_units)::text from public.api_quota_daily where day = public.quota_day(now())),
  '(0,0)', '0 아래로 내려가지 않음');
reset role;

select * from finish();
rollback;
