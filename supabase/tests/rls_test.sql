-- task-002 RLS·권한·추가 전용·작업 중복 테스트 (supabase test db)
-- 양성 대조는 이 파일에서 직접 넣은 픽스처만 쓴다(시드에 기대지 않음).
begin;
create extension if not exists pgtap with schema extensions;
select plan(50);

-- 1. 전 테이블 RLS 활성
select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity),
  0, 'public 전 테이블 relrowsecurity = true');
select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'),
  16, 'public 테이블 16개(05_DATA_MODEL 표 11개 + task-006 api_quota_daily + task-020 제작 4개)');

-- 픽스처: 전용 워크스페이스와 11개 테이블 각 1행, 구성원·비구성원 사용자
insert into auth.users (id, email, aud, role) values
  ('11111111-1111-4111-8111-111111111111', 'member@test.local', 'authenticated', 'authenticated'),
  ('22222222-2222-4222-8222-222222222222', 'outsider@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('aaaaaaaa-0000-4000-8000-000000000001', 'test-ws');
insert into public.workspace_members (workspace_id, user_id, role) values
  ('aaaaaaaa-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'member');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('aaaaaaaa-0000-4000-8000-000000000002', 'aaaaaaaa-0000-4000-8000-000000000001', 'test-profile', 'KR', 10);
insert into public.broadcaster_channels (workspace_id, channel_id, channel_title) values
  ('aaaaaaaa-0000-4000-8000-000000000001', 'UCtest', 'test-channel');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('aaaaaaaa-0000-4000-8000-000000000003', 'aaaaaaaa-0000-4000-8000-000000000001', 'test-worker', 'hash');
insert into public.jobs (id, workspace_id, kind, status, idempotency_key) values
  ('aaaaaaaa-0000-4000-8000-000000000004', 'aaaaaaaa-0000-4000-8000-000000000001', 'collect', 'retrying', 'fx-1');
insert into public.job_profile_runs (workspace_id, job_id, profile_id, position) values
  ('aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000004', 'aaaaaaaa-0000-4000-8000-000000000002', 0);
insert into public.worker_heartbeats (worker_id, workspace_id, current_job_id) values
  ('aaaaaaaa-0000-4000-8000-000000000003', 'aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000004');
insert into public.candidates (id, workspace_id, video_id, title) values
  ('aaaaaaaa-0000-4000-8000-000000000005', 'aaaaaaaa-0000-4000-8000-000000000001', 'fx-video', 'fx');
insert into public.observations (id, workspace_id, candidate_id, observed_at, view_count, job_id) values
  ('aaaaaaaa-0000-4000-8000-000000000006', 'aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000005',
   now(), 10, 'aaaaaaaa-0000-4000-8000-000000000004');
insert into public.candidate_verdicts (workspace_id, candidate_id, profile_id, status) values
  ('aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000005', 'aaaaaaaa-0000-4000-8000-000000000002', 'pending');

-- 2. 구성원(양성 대조): 자기 워크스페이스 픽스처 1행씩, workers는 거부
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
select is((select count(*)::int from public.workspaces), 1, '구성원: workspaces 1행');
select is((select count(*)::int from public.workspace_members), 1, '구성원: workspace_members 본인 행만');
select is((select count(*)::int from public.profiles), 1, '구성원: profiles 1행');
select is((select count(*)::int from public.broadcaster_channels), 1, '구성원: broadcaster_channels 1행');
select is((select count(*)::int from public.jobs), 1, '구성원: jobs 1행');
select is((select count(*)::int from public.job_profile_runs), 1, '구성원: job_profile_runs 1행');
select is((select count(*)::int from public.worker_heartbeats), 1, '구성원: worker_heartbeats 1행');
select is((select count(*)::int from public.candidates), 1, '구성원: candidates 1행');
select is((select count(*)::int from public.observations), 1, '구성원: observations 1행');
select is((select count(*)::int from public.candidate_verdicts), 1, '구성원: candidate_verdicts 1행');
select throws_ok($$select * from public.workers$$, '42501', null, '구성원: workers select 거부');

-- 3. 구성원 쓰기 거부(insert·update·delete)
select throws_ok(
  $$insert into public.candidates (workspace_id, video_id, title) values ('aaaaaaaa-0000-4000-8000-000000000001', 'x', 'x')$$,
  '42501', null, '구성원: candidates insert 거부');
select throws_ok($$update public.candidates set title = 'y'$$, '42501', null, '구성원: candidates update 거부');
select throws_ok($$delete from public.candidates$$, '42501', null, '구성원: candidates delete 거부');
select throws_ok($$update public.profiles set name = 'y'$$, '42501', null, '구성원: profiles update 거부');
select throws_ok($$delete from public.jobs$$, '42501', null, '구성원: jobs delete 거부');
select throws_ok($$delete from public.observations$$, '42501', null, '구성원: observations delete 거부');
select throws_ok($$update public.workspace_members set role = 'owner'$$, '42501', null, '구성원: workspace_members update 거부');

-- 4. 비구성원: 10개 테이블 0행, workers 거부, insert 거부
select set_config('request.jwt.claims', '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
select is((select count(*)::int from public.workspaces), 0, '비구성원: workspaces 0행');
select is((select count(*)::int from public.workspace_members), 0, '비구성원: workspace_members 0행');
select is((select count(*)::int from public.profiles), 0, '비구성원: profiles 0행');
select is((select count(*)::int from public.broadcaster_channels), 0, '비구성원: broadcaster_channels 0행');
select is((select count(*)::int from public.jobs), 0, '비구성원: jobs 0행');
select is((select count(*)::int from public.job_profile_runs), 0, '비구성원: job_profile_runs 0행');
select is((select count(*)::int from public.worker_heartbeats), 0, '비구성원: worker_heartbeats 0행');
select is((select count(*)::int from public.candidates), 0, '비구성원: candidates 0행');
select is((select count(*)::int from public.observations), 0, '비구성원: observations 0행');
select is((select count(*)::int from public.candidate_verdicts), 0, '비구성원: candidate_verdicts 0행');
select throws_ok($$select * from public.workers$$, '42501', null, '비구성원: workers select 거부');
select throws_ok(
  $$insert into public.profiles (workspace_id, name, market, max_growth_pct) values ('aaaaaaaa-0000-4000-8000-000000000001', 'x', 'KR', 1)$$,
  '42501', null, '비구성원: profiles insert 거부');

-- 5. anon: 조회·헬퍼 실행 거부
reset role;
set local role anon;
select throws_ok($$select * from public.candidates$$, '42501', null, 'anon: candidates select 거부');
select throws_ok(
  $$select public.is_workspace_member('aaaaaaaa-0000-4000-8000-000000000001')$$,
  '42501', null, 'anon: is_workspace_member 실행 거부');

-- 6. 잔여 권한 0건(has_table_privilege·has_function_privilege)
reset role;
select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and has_table_privilege('anon', c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')),
  0, '잔여 권한: anon 테이블 권한 0건');
select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and has_table_privilege('authenticated', c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')),
  0, '잔여 권한: authenticated 쓰기 권한 0건');
select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and has_table_privilege('authenticated', c.oid, 'SELECT')),
  14, '잔여 권한: authenticated select는 workers 뺀 14개(제작 4개 포함)');
select ok(not has_table_privilege('authenticated', 'public.workers', 'SELECT'), '잔여 권한: authenticated workers select 없음');
select is(
  (select count(*)::int from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and has_function_privilege('anon', p.oid, 'EXECUTE')),
  0, '잔여 권한: anon 함수 실행 0건');

-- 7. 기본 권한: 새로 만드는 테이블·함수·시퀀스에 브라우저 역할 권한 없음
create table public.zz_default_priv_probe (id bigint generated always as identity primary key);
create function public.zz_default_priv_probe_fn() returns int language sql as $$ select 1 $$;
select ok(not has_table_privilege('anon', 'public.zz_default_priv_probe', 'SELECT, INSERT, UPDATE, DELETE'),
  '기본 권한: 새 테이블 anon 권한 없음');
select ok(not has_table_privilege('authenticated', 'public.zz_default_priv_probe', 'SELECT, INSERT, UPDATE, DELETE'),
  '기본 권한: 새 테이블 authenticated 권한 없음');
select ok(not has_sequence_privilege('authenticated', 'public.zz_default_priv_probe_id_seq', 'USAGE, SELECT, UPDATE'),
  '기본 권한: 새 시퀀스 authenticated 권한 없음');
select ok(not has_function_privilege('anon', 'public.zz_default_priv_probe_fn()', 'EXECUTE'),
  '기본 권한: 새 함수 anon 실행 없음');
select ok(not has_function_privilege('authenticated', 'public.zz_default_priv_probe_fn()', 'EXECUTE'),
  '기본 권한: 새 함수 authenticated 실행 없음');

-- 8. 활성 작업(queued·running·retrying) 중복 금지 — 픽스처 job은 collect·retrying
select throws_ok(
  $$insert into public.jobs (workspace_id, kind, status, idempotency_key) values ('aaaaaaaa-0000-4000-8000-000000000001', 'collect', 'queued', 'fx-2')$$,
  '23505', null, 'jobs: retrying 있을 때 queued 중복 거부');
select throws_ok(
  $$insert into public.jobs (workspace_id, kind, status, idempotency_key) values ('aaaaaaaa-0000-4000-8000-000000000001', 'collect', 'running', 'fx-3')$$,
  '23505', null, 'jobs: retrying 있을 때 running 중복 거부');
select lives_ok(
  $$insert into public.jobs (workspace_id, kind, status, idempotency_key) values ('aaaaaaaa-0000-4000-8000-000000000001', 'collect', 'done', 'fx-4')$$,
  'jobs: 종료 상태(done)는 중복 허용');
select lives_ok(
  $$insert into public.jobs (workspace_id, kind, status, idempotency_key) values ('aaaaaaaa-0000-4000-8000-000000000001', 'verify', 'queued', 'fx-5')$$,
  'jobs: 다른 종류(verify) queued 허용');
select throws_ok(
  $$insert into public.jobs (workspace_id, kind, status, idempotency_key) values ('aaaaaaaa-0000-4000-8000-000000000001', 'verify', 'retrying', 'fx-6')$$,
  '23505', null, 'jobs: queued 있을 때 retrying 중복 거부');

-- 9. observations 추가 전용(service_role 포함)
set local role service_role;
select throws_ok(
  $$update public.observations set view_count = 1 where id = 'aaaaaaaa-0000-4000-8000-000000000006'$$,
  '23001', null, 'service_role: observations update 예외');

reset role;
select * from finish();
rollback;
