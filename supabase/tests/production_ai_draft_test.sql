-- task-029 AI 초안(000018): reserve_ai_draft·create_ai_draft_revision·fail_ai_draft 테스트
-- 근거: tasks/task-029.md#착수-결정 H1·H2·H3
begin;
create extension if not exists pgtap with schema extensions;
select plan(30);

insert into auth.users (id, email, aud, role) values
  ('66666666-6666-4666-8666-666666666666', 'prod-ai@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('eeeeeeee-0000-4000-8000-000000000001', 'prod-ai-a'),
  ('eeeeeeee-0000-4000-8000-000000000002', 'prod-ai-b');

-- 작업: 11 review(미승인 rev1) · 12 inspect · 13 review(variety) · 14 review(상한 도달) · 15 review(다른 키 작업)
insert into public.production_jobs
  (id, workspace_id, title, format, segment_len_sec, preset_version, idempotency_key, status, ai_draft_count) values
  ('eeeeeeee-0000-4000-8000-000000000011', 'eeeeeeee-0000-4000-8000-000000000001', 'j11', 'category', 60, 'category-1080-v1', 'k11', 'review', 0),
  ('eeeeeeee-0000-4000-8000-000000000012', 'eeeeeeee-0000-4000-8000-000000000001', 'j12', 'category', 60, 'category-1080-v1', 'k12', 'inspect', 0),
  ('eeeeeeee-0000-4000-8000-000000000013', 'eeeeeeee-0000-4000-8000-000000000001', 'j13', 'variety', 60, 'variety-1080-v1', 'k13', 'review', 0),
  ('eeeeeeee-0000-4000-8000-000000000014', 'eeeeeeee-0000-4000-8000-000000000001', 'j14', 'category', 60, 'category-1080-v1', 'k14', 'review', 3),
  ('eeeeeeee-0000-4000-8000-000000000015', 'eeeeeeee-0000-4000-8000-000000000001', 'j15', 'category', 60, 'category-1080-v1', 'k15', 'review', 0);
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, spec, approved_at) values
  ('eeeeeeee-0000-4000-8000-000000000031', 'eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011', 1, '{"user": "edit"}', null);
update public.production_jobs j set current_revision_id = r.id
  from public.edit_revisions r where r.job_id = j.id;

-- 1. 칼럼·권한
select col_not_null('public', 'production_jobs', 'ai_draft_requests', 'ai_draft_requests not null');
select ok(not has_function_privilege('authenticated',
  'public.reserve_ai_draft(uuid, uuid, uuid, text, integer)', 'execute'), 'authenticated reserve 실행 불가');
select ok(not has_function_privilege('anon',
  'public.create_ai_draft_revision(uuid, uuid, uuid, text, jsonb, jsonb)', 'execute'), 'anon create 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.fail_ai_draft(uuid, uuid, text)', 'execute'), 'authenticated fail 실행 불가');
select ok(has_function_privilege('service_role',
  'public.reserve_ai_draft(uuid, uuid, uuid, text, integer)', 'execute'), 'service_role reserve 실행 가능');
select ok(not has_column_privilege('authenticated', 'public.production_jobs', 'ai_draft_requests', 'update'),
  'authenticated 요청 기록 수정 불가');

-- 2. 예약(H2): 횟수+1·직전 rev_no·pending 기록
select is(
  (public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-1', 3) ->> 'ai_draft_count')::int, 1, '예약: 횟수 1');
select is((select ai_draft_count from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000011'),
  1, '작업 ai_draft_count = 1');
select is((select ai_draft_requests -> 0 ->> 'status' || ':' || (ai_draft_requests -> 0 ->> 'base_rev_no')
  from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000011'), 'pending:1', '요청 pending, 직전 rev_no 1');
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-1', 3)$$,
  'NR018', null, '같은 키 처리 중 → NR018');
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-2', 3)$$,
  'NR017', null, '같은 작업 60초 내 새 키 → NR017');
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000015',
    '66666666-6666-4666-8666-666666666666', 'ai-1', 3)$$,
  'NR011', null, '다른 작업에 쓴 키 → NR011');

-- 3. 리비전 생성: 새 rev_no·origin·현재 리비전 이동·기존 편집 보존
select is(
  (public.create_ai_draft_revision('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-1', '{"ai": true}', '{"errors": [], "warnings": []}')
    -> 'revision' ->> 'rev_no')::int, 2, '새 rev_no 2(미승인 rev1이어도 덮어쓰지 않음)');
select is((select origin from public.edit_revisions
  where job_id = 'eeeeeeee-0000-4000-8000-000000000011' and rev_no = 2), 'ai_draft', 'origin = ai_draft');
select is((select spec from public.edit_revisions where id = 'eeeeeeee-0000-4000-8000-000000000031'),
  '{"user": "edit"}'::jsonb, '사용자 편집 rev1 보존');
select is((select r.rev_no from public.production_jobs j join public.edit_revisions r on r.id = j.current_revision_id
  where j.id = 'eeeeeeee-0000-4000-8000-000000000011'), 2, '현재 리비전이 rev2로 이동');
select is((select ai_draft_requests -> 0 ->> 'status' from public.production_jobs
  where id = 'eeeeeeee-0000-4000-8000-000000000011'), 'done', '요청 done');
select throws_ok(
  $$select public.create_ai_draft_revision('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-1', '{}', '{}')$$,
  'NR010', null, '이미 끝난 요청으로 다시 생성 불가');

-- 4. 같은 키 재요청: 기존 결과, 횟수 증가 없음
select is(
  public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-1', 3) -> 'revision' ->> 'rev_no', '2', '재요청: 기존 rev2');
select is((select ai_draft_count from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000011'),
  1, '재요청은 횟수 그대로');

-- 5. 상태·형식·상한(H1·H3)
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000012',
    '66666666-6666-4666-8666-666666666666', 'ai-3', 3)$$,
  'NR010', '현재 상태(inspect)에서는 할 수 없습니다.', 'review 아님 → NR010');
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000013',
    '66666666-6666-4666-8666-666666666666', 'ai-4', 3)$$,
  'NR010', null, 'variety → NR010');
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000014',
    '66666666-6666-4666-8666-666666666666', 'ai-5', 3)$$,
  'NR016', null, '상한 3 도달 → NR016');
select throws_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000002', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'ai-6', 3)$$,
  'NR009', null, '타 워크스페이스 → NR009');
select is((select sum(jsonb_array_length(ai_draft_requests))::int from public.production_jobs
  where id in ('eeeeeeee-0000-4000-8000-000000000012', 'eeeeeeee-0000-4000-8000-000000000013',
               'eeeeeeee-0000-4000-8000-000000000014')), 0, '거부된 요청은 기록 없음');

-- 6. 실패 기록: 횟수 유지, 같은 키 재요청은 failed 결과
select lives_ok(
  $$select public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000015',
    '66666666-6666-4666-8666-666666666666', 'ai-7', 3)$$, '작업 15 예약');
select lives_ok(
  $$select public.fail_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000015', 'ai-7')$$,
  '실패 기록');
select is(
  public.reserve_ai_draft('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000015',
    '66666666-6666-4666-8666-666666666666', 'ai-7', 3) ->> 'request_status', 'failed', '같은 키 재요청: failed');
select is((select ai_draft_count from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000015'),
  1, '실패도 1회로 계수');

-- 7. 같은 키 재요청은 60초 간격 검사보다 먼저(기존 결과 200)
select is((select ai_draft_count from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000014'),
  3, '상한 거부는 횟수 그대로');

select * from finish();
rollback;
