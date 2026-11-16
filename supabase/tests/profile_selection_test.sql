-- task-010 set_profile_selection RPC 테스트 (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(17);

insert into public.workspaces (id, name) values
  ('bbbbbbbb-0000-4000-8000-000000000001', 'sel-ws'),
  ('bbbbbbbb-0000-4000-8000-000000000002', 'sel-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct, updated_at) values
  ('bbbbbbbb-0000-4000-8000-0000000000a1', 'bbbbbbbb-0000-4000-8000-000000000001', 'p1', 'KR', 10, '2026-01-01T00:00:00.123456Z'),
  ('bbbbbbbb-0000-4000-8000-0000000000a2', 'bbbbbbbb-0000-4000-8000-000000000001', 'p2', 'KR', 10, '2026-01-01T00:00:00.123456Z'),
  ('bbbbbbbb-0000-4000-8000-0000000000a3', 'bbbbbbbb-0000-4000-8000-000000000001', 'p3', 'JP', 10, '2026-01-01T00:00:00.123456Z'),
  ('bbbbbbbb-0000-4000-8000-0000000000a4', 'bbbbbbbb-0000-4000-8000-000000000001', 'p4', 'JP', 10, '2026-01-01T00:00:00.123456Z'),
  ('bbbbbbbb-0000-4000-8000-0000000000b1', 'bbbbbbbb-0000-4000-8000-000000000002', 'o1', 'KR', 10, '2026-01-01T00:00:00.123456Z');

-- 1. 함수 속성
select is(
  (select prosecdef from pg_proc where oid = 'public.set_profile_selection(uuid, uuid[])'::regprocedure),
  false, 'security invoker');
select is(
  (select proconfig from pg_proc where oid = 'public.set_profile_selection(uuid, uuid[])'::regprocedure),
  array['search_path=""'], 'search_path 비움');

-- 2. 브라우저 역할 실행 거부
set local role authenticated;
select throws_ok(
  $$select public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001', '{}')$$,
  '42501', null, 'authenticated 실행 거부');
reset role;
set local role anon;
select throws_ok(
  $$select public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001', '{}')$$,
  '42501', null, 'anon 실행 거부');
reset role;

set local role service_role;
-- 3. 정상 선택(중복 id 제거, 순서 유지)
select is(
  public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001',
    array['bbbbbbbb-0000-4000-8000-0000000000a2', 'bbbbbbbb-0000-4000-8000-0000000000a1',
          'bbbbbbbb-0000-4000-8000-0000000000a2']::uuid[]),
  array['bbbbbbbb-0000-4000-8000-0000000000a2', 'bbbbbbbb-0000-4000-8000-0000000000a1']::uuid[],
  'service_role: 중복 제거 후 2개 선택');
select is(
  (select array_agg(id order by id) from public.profiles
    where workspace_id = 'bbbbbbbb-0000-4000-8000-000000000001' and selected),
  array['bbbbbbbb-0000-4000-8000-0000000000a1', 'bbbbbbbb-0000-4000-8000-0000000000a2']::uuid[],
  '선택된 행 = 요청 id');
select is(
  (select count(*)::int from public.profiles
    where workspace_id in ('bbbbbbbb-0000-4000-8000-000000000001', 'bbbbbbbb-0000-4000-8000-000000000002')
      and updated_at <> '2026-01-01T00:00:00.123456Z'),
  0, 'updated_at 변경 없음');

-- 4. 4개 거부, 상태 유지
select throws_ok(
  $$select public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001',
    array['bbbbbbbb-0000-4000-8000-0000000000a1', 'bbbbbbbb-0000-4000-8000-0000000000a2',
          'bbbbbbbb-0000-4000-8000-0000000000a3', 'bbbbbbbb-0000-4000-8000-0000000000a4']::uuid[])$$,
  'NR001', null, '4개 선택 거부');
-- 5. 타 워크스페이스 id·없는 id 거부
select throws_ok(
  $$select public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001',
    array['bbbbbbbb-0000-4000-8000-0000000000a3', 'bbbbbbbb-0000-4000-8000-0000000000b1']::uuid[])$$,
  'NR002', null, '타 워크스페이스 id 거부');
select throws_ok(
  $$select public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001',
    array['bbbbbbbb-0000-4000-8000-0000000000ff']::uuid[])$$,
  'NR002', null, '없는 id 거부');
select is(
  (select count(*)::int from public.profiles
    where workspace_id = 'bbbbbbbb-0000-4000-8000-000000000001' and selected),
  2, '거부 후 선택 상태 유지');
select is(
  (select selected from public.profiles where id = 'bbbbbbbb-0000-4000-8000-0000000000b1'),
  false, '타 워크스페이스 행은 바뀌지 않음');

-- 6. 빈 배열 = 전부 해제
select is(
  public.set_profile_selection('bbbbbbbb-0000-4000-8000-000000000001', '{}'::uuid[]),
  '{}'::uuid[], '빈 배열 허용');
select is(
  (select count(*)::int from public.profiles
    where workspace_id = 'bbbbbbbb-0000-4000-8000-000000000001' and selected),
  0, '빈 배열: 전부 해제');

reset role;
-- 7. max_growth_pct 자릿수(numeric(6,2))·기존 check(0~1000) 유지
select col_type_is('public', 'profiles', 'max_growth_pct', 'numeric(6,2)', 'max_growth_pct numeric(6,2)');
select is(
  (select max_growth_pct::text from public.profiles where id = 'bbbbbbbb-0000-4000-8000-0000000000a1'),
  '10.00', '소수 둘째 자리로 저장');
select throws_ok(
  $$update public.profiles set max_growth_pct = 1000.01 where id = 'bbbbbbbb-0000-4000-8000-0000000000a1'$$,
  '23514', null, 'check 0~1000 유지');

select * from finish();
rollback;
