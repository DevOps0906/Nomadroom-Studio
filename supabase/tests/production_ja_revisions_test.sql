-- task-049 일본어판 리비전(000027): reserve_translation·create_ja_translation·fail_translation·
-- save_ja_revision·approve_ja_revision 테스트. 근거: tasks/task-049.md#착수-결정 J2·J5·J8·J9
begin;
create extension if not exists pgtap with schema extensions;
select plan(38);

insert into auth.users (id, email, aud, role) values
  ('49494949-4949-4949-8949-494949494949', 'prod-ja@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('49000000-0000-4000-8000-000000000001', 'prod-ja-a');

-- 11: review(현재 ko 승인) · 12: review(현재 ko 미승인) · 13: 다른 키 작업(현재 ko 승인)
insert into public.production_jobs
  (id, workspace_id, title, format, segment_len_sec, preset_version, idempotency_key, status) values
  ('49000000-0000-4000-8000-000000000011', '49000000-0000-4000-8000-000000000001', 'j11', 'category', 60, 'category-1080-v1', 'k11', 'review'),
  ('49000000-0000-4000-8000-000000000012', '49000000-0000-4000-8000-000000000001', 'j12', 'category', 60, 'category-1080-v1', 'k12', 'review'),
  ('49000000-0000-4000-8000-000000000013', '49000000-0000-4000-8000-000000000001', 'j13', 'category', 60, 'category-1080-v1', 'k13', 'inspect');
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, spec, approved_at) values
  ('49000000-0000-4000-8000-000000000031', '49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011', 1, '{"lang": "ko"}', now()),
  ('49000000-0000-4000-8000-000000000032', '49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000012', 1, '{"lang": "ko"}', null),
  ('49000000-0000-4000-8000-000000000033', '49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000013', 1, '{"lang": "ko"}', now());
update public.production_jobs j set current_revision_id = r.id
  from public.edit_revisions r where r.job_id = j.id;

-- 1. 칼럼·권한
select col_not_null('public', 'production_jobs', 'translate_requests', 'translate_requests not null');
select col_default_is('public', 'production_jobs', 'translate_count', '0', 'translate_count 기본 0');
select ok(not has_function_privilege('authenticated',
  'public.reserve_translation(uuid, uuid, uuid, text, uuid, integer)', 'execute'), 'authenticated reserve 실행 불가');
select ok(not has_function_privilege('anon',
  'public.create_ja_translation(uuid, uuid, uuid, text, jsonb, jsonb)', 'execute'), 'anon create 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.save_ja_revision(uuid, uuid, uuid, integer, jsonb, jsonb)', 'execute'), 'authenticated save 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.approve_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)', 'execute'), 'authenticated approve 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public._ja_writable(uuid, uuid)', 'execute'), 'authenticated 내부 함수 실행 불가');
select ok(has_function_privilege('service_role',
  'public.approve_ja_revision(uuid, uuid, uuid, integer, timestamptz, jsonb)', 'execute'), 'service_role approve 실행 가능');
select ok(not has_column_privilege('authenticated', 'public.production_jobs', 'translate_requests', 'update'),
  'authenticated 번역 기록 수정 불가');
select ok((select p.prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname = 'reserve_translation') like '%pg_advisory_xact_lock%',
  '예약은 워크스페이스·키 advisory 잠금으로 직렬화');

-- 2. 예약(J2·J9): 현재 승인 ko만, 별도 카운터·종류 기록
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000012',
    '49494949-4949-4949-8949-494949494949', 'tr-0', '49000000-0000-4000-8000-000000000032', 3)$$,
  'NR012', null, '미승인 ko → NR012');
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-0', '49000000-0000-4000-8000-000000000033', 3)$$,
  'NR012', null, '다른 작업 리비전 → NR012');
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000002', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-0', '49000000-0000-4000-8000-000000000031', 3)$$,
  'NR009', null, '다른 워크스페이스 → NR009');
select is(
  (public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-1', '49000000-0000-4000-8000-000000000031', 3)
    ->> 'translate_count')::int, 1, '예약: 번역 횟수 1');
select is((select translate_requests -> 0 ->> 'kind' || ':' || (translate_requests -> 0 ->> 'status')
            || ':' || ai_draft_count
  from public.production_jobs where id = '49000000-0000-4000-8000-000000000011'),
  'translate:pending:0', '종류 기록·pending, AI 초안 횟수와 별도');
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-1', '49000000-0000-4000-8000-000000000031', 3)$$,
  'NR018', null, '같은 키 처리 중 → NR018');
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-2', '49000000-0000-4000-8000-000000000031', 3)$$,
  'NR017', null, '60초 내 새 키 → NR017');
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000013',
    '49494949-4949-4949-8949-494949494949', 'tr-1', '49000000-0000-4000-8000-000000000033', 3)$$,
  'NR011', null, '다른 작업에 쓴 키 → NR011');

-- 3. 생성: 새 ja rev·derived_from·현재 ja 이동·job 상태 불변
select is(
  (public.create_ja_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-1', '{"lang": "ja"}', '{"errors": [], "warnings": []}')
    -> 'revision' ->> 'rev_no')::int, 1, 'ja rev_no 1');
select is((select r.lang || ':' || r.origin || ':' || r.derived_from::text from public.edit_revisions r
  join public.production_jobs j on j.current_ja_revision_id = r.id
  where j.id = '49000000-0000-4000-8000-000000000011'),
  'ja:ai_draft:49000000-0000-4000-8000-000000000031', '현재 ja = 파생 리비전');
select is((select status || ':' || current_revision_id::text from public.production_jobs
  where id = '49000000-0000-4000-8000-000000000011'),
  'review:49000000-0000-4000-8000-000000000031', 'job 상태·ko 현재 불변');
select is(
  (public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-1', '49000000-0000-4000-8000-000000000031', 3)
    ->> 'replay')::boolean, true, '같은 키 재요청 = replay');
select throws_ok(
  $$select public.create_ja_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-1', '{}', '{}')$$,
  'NR010', null, '끝난 요청으로 생성 → NR010');

-- 4. 저장(A-12 ja): 미승인 갱신·잠금 불일치
select is((public.save_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 1, '{"lang": "ja", "edit": 1}', '{"errors": [], "warnings": []}')
    ->> 'rev_no')::int, 1, '미승인 ja 제자리 저장');
select throws_ok(
  $$select public.save_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 2, '{}', '{}')$$,
  'NR011', null, 'base_rev_no 불일치 → NR011');
select throws_ok(
  $$select public.save_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000013',
    '49494949-4949-4949-8949-494949494949', 1, '{}', '{}')$$,
  'NR010', null, 'ja 리비전 없음 → NR010');

-- 5. 승인(A-13 ja)
select throws_ok(
  $$select public.approve_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 1, '2000-01-01', '{}')$$,
  'NR011', null, 'updated_at 불일치 → NR011');
select is((public.approve_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 1,
    (select r.updated_at from public.edit_revisions r join public.production_jobs j on j.current_ja_revision_id = r.id
      where j.id = '49000000-0000-4000-8000-000000000011'), '{"errors": [], "warnings": []}')
    ->> 'rev_no')::int, 1, 'ja 승인');
select is((select status from public.production_jobs where id = '49000000-0000-4000-8000-000000000011'),
  'review', '승인 후에도 job 상태 불변');
select is((public.save_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 1, '{"lang": "ja", "edit": 2}', '{"errors": [], "warnings": []}')
    ->> 'rev_no')::int, 2, '승인본 저장 → 새 ja rev_no 2');
select is((select r.derived_from::text from public.edit_revisions r
  join public.production_jobs j on j.current_ja_revision_id = r.id
  where j.id = '49000000-0000-4000-8000-000000000011'),
  '49000000-0000-4000-8000-000000000031', '새 ja rev도 같은 derived_from');

-- 6. ja 렌더 진행 중이면 저장·예약 409
insert into public.render_runs (id, workspace_id, job_id, revision_id, lang, attempt, idempotency_key, preset_version)
  select '49000000-0000-4000-8000-000000000071', '49000000-0000-4000-8000-000000000001',
    '49000000-0000-4000-8000-000000000011', r.id, 'ja', 1, 'ja-r1', 'category-1080-v1'
  from public.edit_revisions r
  where r.job_id = '49000000-0000-4000-8000-000000000011' and r.lang = 'ja' and r.rev_no = 1;
select throws_ok(
  $$select public.save_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 2, '{}', '{}')$$,
  'NR010', null, 'ja 렌더 중 저장 → NR010');
update public.production_jobs set translate_requests = '[]' where id = '49000000-0000-4000-8000-000000000011';
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-3', '49000000-0000-4000-8000-000000000031', 3)$$,
  'NR010', null, 'ja 렌더 중 예약 → NR010');
delete from public.render_runs where id = '49000000-0000-4000-8000-000000000071';

-- 7. 상한(NR016)
update public.production_jobs set translate_count = 3 where id = '49000000-0000-4000-8000-000000000011';
select throws_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 'tr-4', '49000000-0000-4000-8000-000000000031', 3)$$,
  'NR016', null, '작업당 상한 → NR016');

-- 8. ko 변경(J2·J8): ko 현재 미승인이면 저장 409, ko 새 승인본이면 ja 승인 차단
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, spec, approved_at) values
  ('49000000-0000-4000-8000-000000000034', '49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011', 2, '{"lang": "ko"}', null);
update public.production_jobs set current_revision_id = '49000000-0000-4000-8000-000000000034'
  where id = '49000000-0000-4000-8000-000000000011';
select throws_ok(
  $$select public.save_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 2, '{}', '{}')$$,
  'NR010', null, 'ko 미승인 중 ja 저장 → NR010');
update public.edit_revisions set approved_at = now() where id = '49000000-0000-4000-8000-000000000034';
select throws_ok(
  $$select public.approve_ja_revision('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000011',
    '49494949-4949-4949-8949-494949494949', 2,
    (select r.updated_at from public.edit_revisions r join public.production_jobs j on j.current_ja_revision_id = r.id
      where j.id = '49000000-0000-4000-8000-000000000011'), '{}')$$,
  'NR010', null, '원본 ko 변경 후 ja 승인 → NR010');

-- 9. 실패 기록
update public.production_jobs set translate_count = 0, translate_requests = '[]'
  where id = '49000000-0000-4000-8000-000000000013';
select lives_ok(
  $$select public.reserve_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000013',
    '49494949-4949-4949-8949-494949494949', 'tr-9', '49000000-0000-4000-8000-000000000033', 3)$$,
  'inspect 작업도 예약 가능(job 상태 무관)');
select public.fail_translation('49000000-0000-4000-8000-000000000001', '49000000-0000-4000-8000-000000000013', 'tr-9');
select is((select translate_requests -> 0 ->> 'status' || ':' || translate_count
  from public.production_jobs where id = '49000000-0000-4000-8000-000000000013'),
  'failed:1', '실패 기록·횟수 유지');

select * from finish();
rollback;
