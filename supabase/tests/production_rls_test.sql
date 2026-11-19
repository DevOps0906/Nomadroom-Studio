-- task-020 제작 스키마 RLS·권한·부분 unique·소속 일관성 FK·Storage 버킷 테스트 (supabase test db)
-- 픽스처는 이 파일에서 직접 넣는다(시드에 기대지 않음).
begin;
create extension if not exists pgtap with schema extensions;
select plan(36);

-- 픽스처: 워크스페이스 A(작업 2건)·B(작업 1건), 구성원(A)·비구성원
insert into auth.users (id, email, aud, role) values
  ('33333333-3333-4333-8333-333333333333', 'prod-member@test.local', 'authenticated', 'authenticated'),
  ('44444444-4444-4444-8444-444444444444', 'prod-outsider@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('cccccccc-0000-4000-8000-000000000001', 'prod-ws-a'),
  ('cccccccc-0000-4000-8000-000000000002', 'prod-ws-b');
insert into public.workspace_members (workspace_id, user_id, role) values
  ('cccccccc-0000-4000-8000-000000000001', '33333333-3333-4333-8333-333333333333', 'member');
insert into public.production_jobs (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key) values
  ('cccccccc-0000-4000-8000-000000000011', 'cccccccc-0000-4000-8000-000000000001', 'job-a1', 60, 'category-v1', 'pj-a1'),
  ('cccccccc-0000-4000-8000-000000000012', 'cccccccc-0000-4000-8000-000000000001', 'job-a2', 60, 'category-v1', 'pj-a2'),
  ('cccccccc-0000-4000-8000-000000000021', 'cccccccc-0000-4000-8000-000000000002', 'job-b1', 60, 'category-v1', 'pj-b1');
insert into public.edit_revisions (id, workspace_id, job_id, rev_no) values
  ('cccccccc-0000-4000-8000-000000000031', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011', 1),
  ('cccccccc-0000-4000-8000-000000000032', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000012', 1),
  ('cccccccc-0000-4000-8000-000000000033', 'cccccccc-0000-4000-8000-000000000002', 'cccccccc-0000-4000-8000-000000000021', 1);
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime) values
  ('cccccccc-0000-4000-8000-000000000041', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011', 'source',
   'cccccccc-0000-4000-8000-000000000001/cccccccc-0000-4000-8000-000000000011/cccccccc-0000-4000-8000-000000000041.mp4', 'video/mp4'),
  ('cccccccc-0000-4000-8000-000000000042', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000012', 'output_mp4',
   'cccccccc-0000-4000-8000-000000000001/cccccccc-0000-4000-8000-000000000012/cccccccc-0000-4000-8000-000000000042.mp4', 'video/mp4'),
  ('cccccccc-0000-4000-8000-000000000043', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011', 'output_mp4',
   'cccccccc-0000-4000-8000-000000000001/cccccccc-0000-4000-8000-000000000011/cccccccc-0000-4000-8000-000000000043.mp4', 'video/mp4'),
  ('cccccccc-0000-4000-8000-000000000044', 'cccccccc-0000-4000-8000-000000000002', 'cccccccc-0000-4000-8000-000000000021', 'source',
   'cccccccc-0000-4000-8000-000000000002/cccccccc-0000-4000-8000-000000000021/cccccccc-0000-4000-8000-000000000044.mp4', 'video/mp4');
-- 실패 run 1건(A1·R1) + B 워크스페이스 run 1건
insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version, status) values
  ('cccccccc-0000-4000-8000-000000000051', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011',
   'cccccccc-0000-4000-8000-000000000031', 'rr-1', 'category-v1', 'failed'),
  ('cccccccc-0000-4000-8000-000000000059', 'cccccccc-0000-4000-8000-000000000002', 'cccccccc-0000-4000-8000-000000000021',
   'cccccccc-0000-4000-8000-000000000033', 'rr-b', 'category-v1', 'queued');

-- 1. RLS 활성
select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relrowsecurity
      and c.relname in ('production_jobs', 'production_assets', 'edit_revisions', 'render_runs')),
  4, '제작 테이블 4개 RLS 활성');

-- 2. 구성원(양성 대조): 자기 워크스페이스 행만
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}', true);
select is((select count(*)::int from public.production_jobs), 2, '구성원: production_jobs 자기 워크스페이스 2행');
select is((select count(*)::int from public.edit_revisions), 2, '구성원: edit_revisions 2행');
select is((select count(*)::int from public.production_assets), 3, '구성원: production_assets 3행');
select is((select count(*)::int from public.render_runs), 1, '구성원: render_runs 1행');

-- 3. 구성원 쓰기 거부
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version)
    values ('cccccccc-0000-4000-8000-000000000001', 'x', 10, 'category-v1')$$,
  '42501', null, '구성원: production_jobs insert 거부');
select throws_ok($$update public.edit_revisions set spec = '{"x":1}'$$, '42501', null, '구성원: edit_revisions update 거부');
select throws_ok($$delete from public.render_runs$$, '42501', null, '구성원: render_runs delete 거부');

-- 4. 비구성원(다른 워크스페이스): 0행
select set_config('request.jwt.claims', '{"sub":"44444444-4444-4444-8444-444444444444","role":"authenticated"}', true);
select is((select count(*)::int from public.production_jobs), 0, '비구성원: production_jobs 0행');
select is((select count(*)::int from public.edit_revisions), 0, '비구성원: edit_revisions 0행');
select is((select count(*)::int from public.production_assets), 0, '비구성원: production_assets 0행');
select is((select count(*)::int from public.render_runs), 0, '비구성원: render_runs 0행');

-- 5. anon: 조회 거부
reset role;
set local role anon;
select throws_ok($$select * from public.production_jobs$$, '42501', null, 'anon: production_jobs select 거부');
select throws_ok($$select * from public.edit_revisions$$, '42501', null, 'anon: edit_revisions select 거부');
select throws_ok($$select * from public.production_assets$$, '42501', null, 'anon: production_assets select 거부');
select throws_ok($$select * from public.render_runs$$, '42501', null, 'anon: render_runs select 거부');

-- 6. 권한: service_role 읽기·쓰기, authenticated 쓰기 없음
reset role;
select is(
  (select count(*)::int from unnest(array['production_jobs', 'production_assets', 'edit_revisions', 'render_runs']) t
    where has_table_privilege('service_role', 'public.' || t, 'SELECT')
      and has_table_privilege('service_role', 'public.' || t, 'INSERT')
      and has_table_privilege('service_role', 'public.' || t, 'UPDATE')
      and has_table_privilege('service_role', 'public.' || t, 'DELETE')),
  4, 'service_role: 4개 테이블 select·insert·update·delete');
select is(
  (select count(*)::int from unnest(array['production_jobs', 'production_assets', 'edit_revisions', 'render_runs']) t
    where has_table_privilege('authenticated', 'public.' || t, 'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
       or has_table_privilege('anon', 'public.' || t, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')),
  0, 'authenticated 쓰기·anon 전 권한 0건');

-- 7. 렌더 부분 unique
set local role service_role;
select lives_ok(
  $$insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version, status, attempt, retry_of)
    values ('cccccccc-0000-4000-8000-000000000052', 'cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011',
            'cccccccc-0000-4000-8000-000000000031', 'rr-2', 'category-v1', 'queued', 2, 'cccccccc-0000-4000-8000-000000000051')$$,
  '같은 (작업, 리비전, 언어)라도 failed run은 제외 → 재시도 queued 허용');
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, idempotency_key, preset_version, status)
    values ('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000012',
            'cccccccc-0000-4000-8000-000000000032', 'rr-3', 'category-v1', 'queued')$$,
  '23505', 'duplicate key value violates unique constraint "render_runs_active_ws_uidx"',
  '동시 렌더 2건째(다른 작업) render_runs_active_ws_uidx 위반');
update public.render_runs set status = 'done' where id = 'cccccccc-0000-4000-8000-000000000052';
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, idempotency_key, preset_version, status)
    values ('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011',
            'cccccccc-0000-4000-8000-000000000031', 'rr-4', 'category-v1', 'queued')$$,
  '23505', 'duplicate key value violates unique constraint "render_runs_active_rev_uidx"',
  '같은 (작업, 리비전, 언어) done 있을 때 2건째 render_runs_active_rev_uidx 위반');
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, lang, idempotency_key, preset_version, status)
    values ('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000012',
            'cccccccc-0000-4000-8000-000000000032', 'ja', 'rr-5', 'category-v1', 'failed')$$,
  '23514', null, 'lang ja는 아직 거부(task-042에서 확장)');

-- 8. 다른 작업의 리비전·자산 참조 = FK 위반
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, idempotency_key, preset_version, status)
    values ('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011',
            'cccccccc-0000-4000-8000-000000000032', 'rr-6', 'category-v1', 'failed')$$,
  '23503', null, 'render_runs: 다른 작업의 리비전 참조 거부');
select throws_ok(
  $$update public.production_jobs set current_revision_id = 'cccccccc-0000-4000-8000-000000000032'
    where id = 'cccccccc-0000-4000-8000-000000000011'$$,
  '23503', null, 'production_jobs: 다른 작업의 리비전을 current_revision_id로 거부');
select throws_ok(
  $$update public.render_runs set mp4_asset_id = 'cccccccc-0000-4000-8000-000000000042'
    where id = 'cccccccc-0000-4000-8000-000000000052'$$,
  '23503', null, 'render_runs: 다른 작업의 자산을 mp4_asset_id로 거부');

-- 9. workspace_id 불일치 자식 거부, 경로 규칙
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, rev_no)
    values ('cccccccc-0000-4000-8000-000000000002', 'cccccccc-0000-4000-8000-000000000011', 2)$$,
  '23503', null, 'edit_revisions: job과 workspace_id 불일치 거부');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime)
    values ('cccccccc-0000-4000-8000-000000000045', 'cccccccc-0000-4000-8000-000000000002', 'cccccccc-0000-4000-8000-000000000011', 'sheet',
            'cccccccc-0000-4000-8000-000000000002/cccccccc-0000-4000-8000-000000000011/cccccccc-0000-4000-8000-000000000045.jpg', 'image/jpeg')$$,
  '23503', null, 'production_assets: job과 workspace_id 불일치 거부');
select throws_ok(
  $$insert into public.production_assets (workspace_id, job_id, kind, storage_path, mime)
    values ('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-000000000011', 'sheet', 'free/name.jpg', 'image/jpeg')$$,
  '23514', null, 'production_assets: 경로 규칙({ws}/{job}/{asset}.{ext}) 위반 거부');

-- 10. 자산 단독 삭제 → 참조 칼럼만 null
update public.render_runs set mp4_asset_id = 'cccccccc-0000-4000-8000-000000000043'
  where id = 'cccccccc-0000-4000-8000-000000000052';
update public.production_assets set render_run_id = 'cccccccc-0000-4000-8000-000000000052'
  where id = 'cccccccc-0000-4000-8000-000000000043';
select lives_ok(
  $$delete from public.production_assets where id = 'cccccccc-0000-4000-8000-000000000043'$$,
  '자산 단독 삭제 성공');
select is(
  (select mp4_asset_id from public.render_runs where id = 'cccccccc-0000-4000-8000-000000000052'),
  null::uuid, '자산 삭제 후 render_runs.mp4_asset_id = null, run 유지');

-- 11. job 삭제 연쇄(현재 리비전·자산·run 순환 참조 포함)
update public.production_jobs set current_revision_id = 'cccccccc-0000-4000-8000-000000000031'
  where id = 'cccccccc-0000-4000-8000-000000000011';
select lives_ok(
  $$delete from public.production_jobs where id = 'cccccccc-0000-4000-8000-000000000011'$$,
  'job 삭제 성공(순환 참조 포함)');
select is(
  (select count(*)::int from public.edit_revisions where job_id = 'cccccccc-0000-4000-8000-000000000011')
  + (select count(*)::int from public.production_assets where job_id = 'cccccccc-0000-4000-8000-000000000011')
  + (select count(*)::int from public.render_runs where job_id = 'cccccccc-0000-4000-8000-000000000011'),
  0, 'job 삭제 시 리비전·자산·run 연쇄 삭제');
select is((select count(*)::int from public.production_jobs where workspace_id = 'cccccccc-0000-4000-8000-000000000001'),
  1, '다른 작업(A2)은 남음');

-- 12. Storage 버킷
reset role;
select is((select public from storage.buckets where id = 'production'), false, 'production 버킷 비공개');
select is((select file_size_limit from storage.buckets where id = 'production'), 524288000::bigint, 'production 버킷 한도 500MB');
select is(
  (select count(*)::int from pg_policies where schemaname = 'storage' and tablename = 'objects'
     and (qual like '%production%' or with_check like '%production%')),
  0, 'storage.objects에 production 정책 없음(서명 URL만)');

select * from finish();
rollback;
