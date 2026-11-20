-- task-022 제작 API 보조(000016): 멱등 키 unique, save/approve_production_revision RPC 테스트
-- 근거: tasks/task-022.md#착수-결정 D1·D2·D3
begin;
create extension if not exists pgtap with schema extensions;
select plan(41);

insert into auth.users (id, email, aud, role) values
  ('55555555-5555-4555-8555-555555555555', 'prod-api@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('dddddddd-0000-4000-8000-000000000001', 'prod-api-a'),
  ('dddddddd-0000-4000-8000-000000000002', 'prod-api-b');

-- 작업: 11 review(미승인 rev1) · 12 inspect(승인 rev1) · 13 failed(render, 승인 rev1)
--       14 failed(prepare, rev1) · 15 draft(rev1) · 16 review(리비전 없음) · 17 review(승인 대상)
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, status, failed_stage, error_code) values
  ('dddddddd-0000-4000-8000-000000000011', 'dddddddd-0000-4000-8000-000000000001', 'j11', 60, 'category-1080-v1', 'k11', 'review', null, null),
  ('dddddddd-0000-4000-8000-000000000012', 'dddddddd-0000-4000-8000-000000000001', 'j12', 60, 'category-1080-v1', 'k12', 'inspect', null, null),
  ('dddddddd-0000-4000-8000-000000000013', 'dddddddd-0000-4000-8000-000000000001', 'j13', 60, 'category-1080-v1', 'k13', 'failed', 'render', 'hook_too_long'),
  ('dddddddd-0000-4000-8000-000000000014', 'dddddddd-0000-4000-8000-000000000001', 'j14', 60, 'category-1080-v1', 'k14', 'failed', 'prepare', 'download_failed'),
  ('dddddddd-0000-4000-8000-000000000015', 'dddddddd-0000-4000-8000-000000000001', 'j15', 60, 'category-1080-v1', 'k15', 'draft', null, null),
  ('dddddddd-0000-4000-8000-000000000016', 'dddddddd-0000-4000-8000-000000000001', 'j16', 60, 'category-1080-v1', 'k16', 'review', null, null),
  ('dddddddd-0000-4000-8000-000000000017', 'dddddddd-0000-4000-8000-000000000001', 'j17', 60, 'category-1080-v1', 'k17', 'review', null, null);
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, approved_at, updated_at) values
  ('dddddddd-0000-4000-8000-000000000031', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011', 1, null, '2026-11-01T00:00:00.123456Z'),
  ('dddddddd-0000-4000-8000-000000000032', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012', 1, now(), '2026-11-01T00:00:00Z'),
  ('dddddddd-0000-4000-8000-000000000033', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000013', 1, now(), '2026-11-01T00:00:00Z'),
  ('dddddddd-0000-4000-8000-000000000034', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000014', 1, null, '2026-11-01T00:00:00Z'),
  ('dddddddd-0000-4000-8000-000000000035', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000015', 1, null, '2026-11-01T00:00:00Z'),
  ('dddddddd-0000-4000-8000-000000000037', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000017', 1, null, '2026-11-01T00:00:00.123456Z');
update public.production_jobs j set current_revision_id = r.id
  from public.edit_revisions r where r.job_id = j.id;

-- 1. 멱등 키(D1)
select col_not_null('public', 'production_jobs', 'idempotency_key', 'idempotency_key not null');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key)
    values ('dddddddd-0000-4000-8000-000000000001', 'dup', 10, 'category-1080-v1', 'k11')$$,
  '23505', null, '같은 워크스페이스 같은 키 거부');
select lives_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key)
    values ('dddddddd-0000-4000-8000-000000000002', 'b', 10, 'category-1080-v1', 'k11')$$,
  '다른 워크스페이스는 같은 키 허용');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version)
    values ('dddddddd-0000-4000-8000-000000000001', 'nokey', 10, 'category-1080-v1')$$,
  '23502', null, '키 없는 작업 거부');
select ok(exists (select 1 from pg_constraint
  where conname = 'production_jobs_workspace_id_idempotency_key_key'), 'unique 제약 이름(API가 찾는 이름)');

-- 1-2. 업로드 원본 ready 1건(D5 경합)
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, status) values
  ('dddddddd-0000-4000-8000-000000000041', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000015', 'source_upload',
   'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000015/dddddddd-0000-4000-8000-000000000041.mp4', 'video/mp4', 'ready'),
  ('dddddddd-0000-4000-8000-000000000042', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000015', 'source_upload',
   'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000015/dddddddd-0000-4000-8000-000000000042.mp4', 'video/mp4', 'pending');
select throws_ok(
  $$update public.production_assets set status = 'ready' where id = 'dddddddd-0000-4000-8000-000000000042'$$,
  '23505', null, '같은 작업의 두 번째 ready 원본 거부(production_assets_one_ready_source_uidx)');

-- 2. 실행 권한: API(service_role)만
select ok(not has_function_privilege('anon',
  'public.save_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)', 'EXECUTE'), 'save: anon 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.save_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)', 'EXECUTE'), 'save: authenticated 실행 불가');
select ok(has_function_privilege('service_role',
  'public.save_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb, jsonb)', 'EXECUTE'), 'save: service_role 실행');
select ok(not has_function_privilege('anon',
  'public.approve_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)', 'EXECUTE'), 'approve: anon 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.approve_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)', 'EXECUTE'), 'approve: authenticated 실행 불가');
select ok(has_function_privilege('service_role',
  'public.approve_production_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)', 'EXECUTE'), 'approve: service_role 실행');

-- 3. save(D2·D3)
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000002', 'dddddddd-0000-4000-8000-000000000011',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{"a":1}', '{"errors":[],"warnings":[]}')$$,
  'NR009', null, 'save: 다른 워크스페이스 작업 NR009');
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
    '55555555-5555-4555-8555-555555555555', 2, '2026-11-01T00:00:00.123456Z', '{"a":1}', '{"errors":[],"warnings":[]}')$$,
  'NR011', null, 'save: base_rev_no 불일치 NR011');
select is(
  (public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00.123456Z', '{"a":1}', '{"errors":[{"code":"shots.gap"}],"warnings":[]}')->>'rev_no')::int,
  1, 'save: 미승인 리비전은 같은 행 갱신');
select is((select spec from public.edit_revisions where id = 'dddddddd-0000-4000-8000-000000000031'),
  '{"a":1}'::jsonb, 'save: 오류가 있어도 spec 저장');
select is((select validation->'errors'->0->>'code' from public.edit_revisions where id = 'dddddddd-0000-4000-8000-000000000031'),
  'shots.gap', 'save: validation 저장');
select is((select count(*)::int from public.edit_revisions where job_id = 'dddddddd-0000-4000-8000-000000000011'),
  1, 'save: 새 행 없음');

-- 3-1. task-059 L3: updated_at 잠금(같은 base 두 번 → NR011, 반환 updated_at으로 연속 저장)
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00.123456Z', '{"a":2}', '{"errors":[],"warnings":[]}')$$,
  'NR011', null, 'save: 같은 base_updated_at 두 번째 NR011');
select is((select spec from public.edit_revisions where id = 'dddddddd-0000-4000-8000-000000000031'),
  '{"a":1}'::jsonb, 'save: NR011이면 앞선 편집 유지');
update public.edit_revisions set updated_at = '2026-11-02T00:00:00.654321Z'
  where id = 'dddddddd-0000-4000-8000-000000000031';
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-02T00:00:00.654322Z', '{"a":3}', '{"errors":[],"warnings":[]}')$$,
  'NR011', null, 'save: 마이크로초 1 차이도 NR011');
select ok(
  (public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-02T00:00:00.654321Z', '{"a":3}', '{"errors":[],"warnings":[]}')
    ->> 'updated_at') is not null, 'save: 마이크로초 일치 저장·updated_at 반환');
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
    '55555555-5555-4555-8555-555555555555', 1, '2000-01-01T00:00:00Z', '{"b":2}', '{"errors":[],"warnings":[]}')$$,
  'NR011', null, 'save: 승인본도 updated_at 불일치 NR011');
select is((select count(*)::int from pg_proc p join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname in ('save_production_revision', 'save_ja_revision')),
  2, 'save 함수 오버로드 없음(각 1개)');

select is(
  (public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{"b":2}', '{"errors":[],"warnings":[]}')->>'rev_no')::int,
  2, 'save: 승인본이면 새 rev_no');
select is((select r.rev_no from public.production_jobs j join public.edit_revisions r on r.id = j.current_revision_id
  where j.id = 'dddddddd-0000-4000-8000-000000000012'), 2, 'save: current_revision_id 이동');
select is((select status from public.production_jobs where id = 'dddddddd-0000-4000-8000-000000000012'),
  'review', 'save: inspect → review');
select is((select spec from public.edit_revisions where id = 'dddddddd-0000-4000-8000-000000000032'),
  '{}'::jsonb, 'save: 승인본은 그대로');
select is((select created_by from public.edit_revisions where job_id = 'dddddddd-0000-4000-8000-000000000012' and rev_no = 2),
  '55555555-5555-4555-8555-555555555555'::uuid, 'save: 새 리비전 created_by');

select lives_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000013',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{"c":3}', '{"errors":[],"warnings":[]}')$$,
  'save: failed(render) 허용');
select is((select status || ':' || coalesce(failed_stage, '-') || ':' || coalesce(error_code, '-')
  from public.production_jobs where id = 'dddddddd-0000-4000-8000-000000000013'),
  'review:-:-', 'save: failed → review, 실패 칸 비움');
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000014',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{}', '{"errors":[],"warnings":[]}')$$,
  'NR010', null, 'save: failed(prepare) NR010');
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000015',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{}', '{"errors":[],"warnings":[]}')$$,
  'NR010', null, 'save: draft NR010');
select throws_ok(
  $$select public.save_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000016',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{}', '{"errors":[],"warnings":[]}')$$,
  'NR010', null, 'save: 리비전 없음 NR010');

-- 4. approve(D2)
select throws_ok(
  $$select public.approve_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000017',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00.123457Z', '{"errors":[],"warnings":[]}')$$,
  'NR011', null, 'approve: 재검증 후 updated_at 바뀜 NR011');
select throws_ok(
  $$select public.approve_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000017',
    '55555555-5555-4555-8555-555555555555', 2, '2026-11-01T00:00:00.123456Z', '{"errors":[],"warnings":[]}')$$,
  'NR011', null, 'approve: rev_no 불일치 NR011');
select throws_ok(
  $$select public.approve_production_revision('dddddddd-0000-4000-8000-000000000002', 'dddddddd-0000-4000-8000-000000000017',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00.123456Z', '{"errors":[],"warnings":[]}')$$,
  'NR009', null, 'approve: 다른 워크스페이스 NR009');
select is(
  public.approve_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000017',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00.123456Z', '{"errors":[],"warnings":[{"code":"items.too_short"}]}')->>'approved_by',
  '55555555-5555-4555-8555-555555555555', 'approve: approved_by 기록');
select ok((select approved_at is not null and validation->'warnings'->0->>'code' = 'items.too_short'
  from public.edit_revisions where id = 'dddddddd-0000-4000-8000-000000000037'), 'approve: approved_at·재검증 결과 저장');
select throws_ok(
  $$select public.approve_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000017',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00.123456Z', '{"errors":[],"warnings":[]}')$$,
  'NR010', null, 'approve: 이미 승인 NR010');
select throws_ok(
  $$select public.approve_production_revision('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000015',
    '55555555-5555-4555-8555-555555555555', 1, '2026-11-01T00:00:00Z', '{"errors":[],"warnings":[]}')$$,
  'NR010', null, 'approve: review 아님 NR010');

select * from finish();
rollback;
