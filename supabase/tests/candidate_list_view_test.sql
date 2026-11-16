-- task-011 candidate_list_v 테스트 (supabase test db). 시드 5건 값은 supabase/seed.sql 기준.
begin;
create extension if not exists pgtap with schema extensions;
select plan(17);

-- 1. 뷰 속성·권한
select is(
  (select reloptions from pg_class where oid = 'public.candidate_list_v'::regclass),
  array['security_invoker=true'], 'security_invoker');
select ok(has_table_privilege('service_role', 'public.candidate_list_v', 'SELECT'), 'service_role select 가능');
select ok(not has_table_privilege('anon', 'public.candidate_list_v', 'SELECT, INSERT, UPDATE, DELETE'),
  'anon 권한 없음');
select ok(not has_table_privilege('authenticated', 'public.candidate_list_v', 'SELECT, INSERT, UPDATE, DELETE'),
  'authenticated 권한 없음');
set local role authenticated;
select throws_ok($$select * from public.candidate_list_v$$, '42501', null, 'authenticated 조회 거부');
reset role;
set local role anon;
select throws_ok($$select * from public.candidate_list_v$$, '42501', null, 'anon 조회 거부');
reset role;

-- 2. 시드 5건 값
select results_eq(
  $$select id::text, display_status, growth_pct, prev_view_count, curr_view_count
      from public.candidate_list_v
     where workspace_id = '00000000-0000-4000-8000-000000000001'
     order by id$$,
  $$values
    ('00000000-0000-4000-8000-000000000201', 'producible', 0.60::numeric, 450000::bigint, 452700::bigint),
    ('00000000-0000-4000-8000-000000000202', 'producible', 0.60, 710000, 714260),
    ('00000000-0000-4000-8000-000000000203', 'pending', null, null, 270000),
    ('00000000-0000-4000-8000-000000000204', 'producible', 12.50, 200000, 225000),
    ('00000000-0000-4000-8000-000000000205', 'used', 0.60, 300000, 301800)$$,
  '시드 5건: 표시 상태·대표 판정 증가율·관측');
select is(
  (select reason from public.candidate_list_v where id = '00000000-0000-4000-8000-000000000203'),
  'no_prev', '203 reason = no_prev(대표 판정 프로필 101)');
select is(
  (select prev_observed_at from public.candidate_list_v where id = '00000000-0000-4000-8000-000000000204'),
  '2026-11-09 03:00:00+00'::timestamptz, '204 prev = 대표 판정(102)의 이전 관측');
select is(
  (select latest_observed_at from public.candidate_list_v where id = '00000000-0000-4000-8000-000000000203'),
  '2026-11-16 03:00:00+00'::timestamptz, 'latest_observed_at = 최신 관측');

-- 3. display_status 규칙(판정 전 = pending, used 우선)
insert into public.workspaces (id, name) values ('dddddddd-0000-4000-8000-000000000001', 'view-ws');
insert into public.candidates (id, workspace_id, video_id, title, rep_status, used) values
  ('dddddddd-0000-4000-8000-0000000000c1', 'dddddddd-0000-4000-8000-000000000001', 'v1', 't1', null, false),
  ('dddddddd-0000-4000-8000-0000000000c2', 'dddddddd-0000-4000-8000-000000000001', 'v2', 't2', 'excluded', true),
  ('dddddddd-0000-4000-8000-0000000000c3', 'dddddddd-0000-4000-8000-000000000001', 'v3', 't3', 'excluded', false);
select is((select display_status from public.candidate_list_v where id = 'dddddddd-0000-4000-8000-0000000000c1'),
  'pending', '판정 전 → pending');
select is((select display_status from public.candidate_list_v where id = 'dddddddd-0000-4000-8000-0000000000c2'),
  'used', 'used=true → used(판정보다 우선)');
select is((select display_status from public.candidate_list_v where id = 'dddddddd-0000-4000-8000-0000000000c3'),
  'excluded', 'used=false → rep_status');
select ok(
  (select growth_pct is null and curr_observed_at is null and latest_observed_at is null
     from public.candidate_list_v where id = 'dddddddd-0000-4000-8000-0000000000c1'),
  '판정·관측 없음 → null');

-- 4. 행 수 = candidates 행 수(판정 여러 개여도 중복 없음)
select is((select count(*)::int from public.candidate_list_v),
  (select count(*)::int from public.candidates), '뷰 행 수 = candidates 행 수');

-- 5. service_role로 조회 가능
set local role service_role;
select is((select count(*)::int from public.candidate_list_v
  where workspace_id = 'dddddddd-0000-4000-8000-000000000001'), 3, 'service_role 조회');
reset role;

-- 6. 다른 워크스페이스 판정은 대표 판정으로 붙지 않는다
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('dddddddd-0000-4000-8000-0000000000a1', 'dddddddd-0000-4000-8000-000000000001', 'p', 'KR', 10);
update public.candidates set rep_profile_id = 'dddddddd-0000-4000-8000-0000000000a1'
 where id = 'dddddddd-0000-4000-8000-0000000000c3';
insert into public.candidate_verdicts (workspace_id, candidate_id, profile_id, status, growth_pct) values
  ('00000000-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-0000000000c3',
   'dddddddd-0000-4000-8000-0000000000a1', 'producible', 1);
select is((select growth_pct from public.candidate_list_v where id = 'dddddddd-0000-4000-8000-0000000000c3'),
  null, '워크스페이스가 다른 판정은 조인하지 않음');

select * from finish();
rollback;
