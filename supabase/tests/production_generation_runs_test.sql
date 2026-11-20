-- task-054 AI 영상 생성(000026): generation_runs RLS·RPC 권한·예산·상태·완료·검수 테스트
-- 근거: tasks/task-054.md#착수-결정 G1~G9. 동시성은 한 세션이라 "확인마다 잠금 뒤 재계산"으로 확인한다.
begin;
create extension if not exists pgtap with schema extensions;
select plan(68);

insert into auth.users (id, email, aud, role) values
  ('77777777-7777-4777-8777-777777777771', 'gen-owner@test.local', 'authenticated', 'authenticated'),
  ('77777777-7777-4777-8777-777777777772', 'gen-member@test.local', 'authenticated', 'authenticated'),
  ('77777777-7777-4777-8777-777777777773', 'gen-other@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('dddddddd-0000-4000-8000-000000000001', 'gen-a'),
  ('dddddddd-0000-4000-8000-000000000002', 'gen-b');
insert into public.workspace_members (workspace_id, user_id, role) values
  ('dddddddd-0000-4000-8000-000000000001', '77777777-7777-4777-8777-777777777771', 'owner'),
  ('dddddddd-0000-4000-8000-000000000001', '77777777-7777-4777-8777-777777777772', 'member'),
  ('dddddddd-0000-4000-8000-000000000002', '77777777-7777-4777-8777-777777777773', 'owner');

-- 작업: 11 쇼핑 draft · 12 쇼핑 draft(상태 거부용) · 13 일반 draft
insert into public.production_jobs
  (id, workspace_id, title, kind, vertical, format, segment_len_sec, preset_version, idempotency_key, status) values
  ('dddddddd-0000-4000-8000-000000000011', 'dddddddd-0000-4000-8000-000000000001', 'g11', 'shopping', 'travel', 'shopping', 60, 'shopping-1080-v1', 'gk11', 'draft'),
  ('dddddddd-0000-4000-8000-000000000012', 'dddddddd-0000-4000-8000-000000000001', 'g12', 'shopping', 'travel', 'shopping', 60, 'shopping-1080-v1', 'gk12', 'draft');
insert into public.production_jobs
  (id, workspace_id, title, format, segment_len_sec, preset_version, idempotency_key, status) values
  ('dddddddd-0000-4000-8000-000000000013', 'dddddddd-0000-4000-8000-000000000001', 'g13', 'category', 60, 'category-1080-v1', 'gk13', 'draft');
-- 사진: 21 권리 own(인물 아님) · 22 권리 없음 · 23 인물·동의 없음 · 24 작업 12의 own 사진
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, status, rights) values
  ('dddddddd-0000-4000-8000-000000000021', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011', 'image',
   'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000011/dddddddd-0000-4000-8000-000000000021.jpg', 'image/jpeg', 'ready',
   '{"basis": "own", "author": "운영자", "has_person": false}'),
  ('dddddddd-0000-4000-8000-000000000022', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011', 'image',
   'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000011/dddddddd-0000-4000-8000-000000000022.jpg', 'image/jpeg', 'ready', null),
  ('dddddddd-0000-4000-8000-000000000023', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011', 'image',
   'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000011/dddddddd-0000-4000-8000-000000000023.jpg', 'image/jpeg', 'ready',
   '{"basis": "own", "has_person": true, "portrait_consent": false}'),
  ('dddddddd-0000-4000-8000-000000000024', 'dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012', 'image',
   'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000012/dddddddd-0000-4000-8000-000000000024.jpg', 'image/jpeg', 'ready',
   '{"basis": "licensed"}');

create temp table t_ids (name text primary key, id uuid);
grant all on t_ids to authenticated, service_role;

-- 1. 칼럼·RLS·권한
select col_default_is('public', 'workspaces', 'gen_monthly_budget_krw', '0', '월 예산 기본 0');
select col_not_null('public', 'workspaces', 'gen_job_cap_krw', '작업당 상한 not null');
select col_default_is('public', 'production_assets', 'reviewed', 'false', 'reviewed 기본 false');
select ok((select relrowsecurity from pg_class where oid = 'public.generation_runs'::regclass), 'generation_runs RLS 켜짐');
select ok(not has_table_privilege('authenticated', 'public.generation_runs', 'insert'), 'authenticated insert 불가');
select ok(not has_table_privilege('authenticated', 'public.generation_runs', 'update'), 'authenticated update 불가');
select ok(has_table_privilege('authenticated', 'public.generation_runs', 'select'), 'authenticated select 가능');
select ok(not has_column_privilege('authenticated', 'public.production_assets', 'reviewed', 'update'), 'authenticated reviewed 수정 불가');
select ok(not has_function_privilege('authenticated',
  'public.confirm_generation_run(uuid, uuid, uuid, uuid)', 'execute'), 'authenticated 확인 실행 불가');
select ok(not has_function_privilege('anon',
  'public.quote_generation_run(uuid, uuid, uuid, text, uuid, text, integer, text, text, text, integer)', 'execute'), 'anon 견적 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.review_generation_run(uuid, uuid, uuid, uuid, jsonb)', 'execute'), 'authenticated 검수 실행 불가');
select ok(not has_function_privilege('authenticated',
  'public.finish_generation_run(uuid, uuid, uuid, text, uuid, text, bigint, integer, text)', 'execute'), 'authenticated 완료 실행 불가');
select ok(has_function_privilege('service_role',
  'public.confirm_generation_run(uuid, uuid, uuid, uuid)', 'execute'), 'service_role 확인 실행 가능');
select throws_ok($$update public.workspaces set gen_monthly_budget_krw = -1
  where id = 'dddddddd-0000-4000-8000-000000000001'$$, '23514', null, '음수 예산 거부');

-- 2. 견적: 0원 예산 거부(G9) → 예산 설정 후 정상
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'q0', 'dddddddd-0000-4000-8000-000000000021', '바다', 5, null, 'xai', 'm', 400)$$,
  'NR019', null, '0원 예산 견적 → NR019');
update public.workspaces set gen_monthly_budget_krw = 10000, gen_job_cap_krw = 6000
  where id = 'dddddddd-0000-4000-8000-000000000001';
insert into t_ids select 'q1', (public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'q1', 'dddddddd-0000-4000-8000-000000000021', '바다 위 노을', 5, '2', 'xai', 'm', 4000) #>> '{run,id}')::uuid;
select is((select status || ':' || billable::text from public.generation_runs where id = (select id from t_ids where name = 'q1')),
  'quoted:false', '견적: quoted·비계상');
select is((public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'q1', 'dddddddd-0000-4000-8000-000000000021', '다른 값', 5, null, 'xai', 'm', 4000)
  ->> 'replay')::boolean, true, '같은 키 견적 → replay');
select is((select count(*)::int from public.generation_runs where idempotency_key = 'q1'), 1, '같은 키 run 1건');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  '77777777-7777-4777-8777-777777777772', 'q1', 'dddddddd-0000-4000-8000-000000000024', '바다', 5, null, 'xai', 'm', 400)$$,
  'NR011', null, '다른 작업에 쓴 키 → NR011');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'qx', 'dddddddd-0000-4000-8000-000000000022', '바다', 5, null, 'xai', 'm', 400)$$,
  'NR012', null, '권리 없는 사진 → NR012');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'qx', 'dddddddd-0000-4000-8000-000000000023', '바다', 5, null, 'xai', 'm', 400)$$,
  'NR012', null, '인물·초상 동의 없음 → NR012');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'qx', 'dddddddd-0000-4000-8000-000000000024', '바다', 5, null, 'xai', 'm', 400)$$,
  'NR012', null, '다른 작업의 사진 → NR012');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000013',
  '77777777-7777-4777-8777-777777777772', 'qx', 'dddddddd-0000-4000-8000-000000000021', '바다', 5, null, 'xai', 'm', 400)$$,
  'NR010', null, '쇼핑 아닌 작업 → NR010');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'qx', 'dddddddd-0000-4000-8000-000000000021', '바다', 5, null, 'xai', 'm', 6001)$$,
  'NR019', null, '작업 상한 초과 견적 → NR019');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'qx', 'dddddddd-0000-4000-8000-000000000021', '바다', 16, null, 'xai', 'm', 400)$$,
  '23514', null, 'duration 16초 거부');
-- 같은 작업 두 번째 견적(아직 계상 없음 → 통과)
insert into t_ids select 'q2', (public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'q2', 'dddddddd-0000-4000-8000-000000000021', '숲', 5, null, 'xai', 'm', 4000) #>> '{run,id}')::uuid;

-- 3. 확인(G7·G3·G9): owner 아님 거부 → owner 확인 → 재확인 replay → 두 번째는 재계산으로 거부
select throws_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1'), '77777777-7777-4777-8777-777777777772')$$,
  'NR020', null, 'owner 아닌 확인 → NR020');
select is((public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1'), '77777777-7777-4777-8777-777777777771') #>> '{run,status}'), 'confirmed', 'owner 확인 → confirmed');
select is((select billable from public.generation_runs where id = (select id from t_ids where name = 'q1')), true, '확인 = 계상');
select is((public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1'), '77777777-7777-4777-8777-777777777771') ->> 'replay')::boolean, true, '재확인 → replay(재계상 없음)');
select throws_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q2'), '77777777-7777-4777-8777-777777777771')$$,
  'NR019', null, '두 번째 확인: 잠금 뒤 재계산으로 작업 상한 초과 → NR019');
select is((select status from public.generation_runs where id = (select id from t_ids where name = 'q2')), 'quoted', '거부된 확인은 quoted 유지');
select is((public._gen_budget('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011')
  ->> 'job_left_krw')::int, 2000, '작업 남은 금액 6000-4000');
select throws_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  gen_random_uuid(), '77777777-7777-4777-8777-777777777771')$$, 'NR009', null, '없는 run → NR009');

-- 4. 제출·진행·완료(G2·G5·G1)
select is((public.mark_generation_submitted('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1'),
  'running', 'req-1', null) ->> 'status'), 'running', '제출 → running');
select throws_ok($$select public.mark_generation_submitted('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1'),
  'running', 'req-2', null)$$, 'NR010', null, 'running 재제출 기록 → NR010');
insert into t_ids select 'tok_old', (public.claim_generation_finalize('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1')) ->> 'finalize_token')::uuid;
select isnt((select id from t_ids where name = 'tok_old'), null, '완료 선점 1회(토큰 발급)');
select is(public.claim_generation_finalize('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1')),
  null, '중복 선점 → null(1건만 완료)');
-- 10분 넘게 멈춘 finalizing 회수
update public.generation_runs set updated_at = now() - interval '11 minutes' where id = (select id from t_ids where name = 'q1');
select is((public.begin_generation_refresh('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1')) ->> 'status'), 'running', '멈춘 finalizing → running 회수');
insert into t_ids select 'tok1', (public.claim_generation_finalize('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1')) ->> 'finalize_token')::uuid;
select isnt((select id from t_ids where name = 'tok1'), (select id from t_ids where name = 'tok_old'), '회수 뒤 다시 선점(새 토큰)');
select throws_ok($$select public.finish_generation_run('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1'), (select id from t_ids where name = 'tok_old'), 'failed',
  null, null, null, null, 'x')$$, 'NR010', null, '회수 전 선점자의 완료 기록 거부(토큰 불일치)');
select is((public.finish_generation_run('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'q1'), (select id from t_ids where name = 'tok1'), 'done',
  'dddddddd-0000-4000-8000-000000000031',
  'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000011/dddddddd-0000-4000-8000-000000000031.mp4',
  1234, 3500, null) #>> '{run,status}'), 'done', '완료 → done');
select is((select kind || ':' || status || ':' || (rights ->> 'basis') || ':' || (rights #>> '{gen,cost_krw}') || ':' || (rights ->> 'author') || ':' || reviewed::text
  from public.production_assets where id = 'dddddddd-0000-4000-8000-000000000031'),
  'source_upload:ready:ai_generated:3500:운영자:false', '결과 = source_upload(ai_generated·gen·입력 권리 승계·미검수)');
select is((select result_asset_id from public.generation_runs where id = (select id from t_ids where name = 'q1')),
  'dddddddd-0000-4000-8000-000000000031'::uuid, 'run.result_asset_id');
select is((public._gen_budget('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011')
  ->> 'monthly_left_krw')::int, 6500, '월 남은 금액 = 예산 - coalesce(actual, est)');

-- 5. 검수(G4)
select is((public.review_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1'), '77777777-7777-4777-8777-777777777772',
  '{"physics": true, "angle": true, "compare": false}') ->> 'reviewed')::boolean, false, '2항목만 → reviewed false');
select is((public.review_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1'), '77777777-7777-4777-8777-777777777772',
  '{"physics": true, "angle": true, "compare": true}') ->> 'reviewed')::boolean, true, '3항목 → reviewed true(요청자 본인 허용)');
select is((select reviewed from public.production_assets where id = 'dddddddd-0000-4000-8000-000000000031'), true, '자산 reviewed 칼럼 갱신');
select throws_ok($$select public.review_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 'q1'), '77777777-7777-4777-8777-777777777772', '{"physics": "yes", "angle": true, "compare": true}')$$,
  'NR012', null, '검수 값 형식 거부');

-- 6. 플랫폼 거부 = 비계상, 저장 거부 = 계상 유지(G1·G2) — 작업 12
update public.workspaces set gen_job_cap_krw = 100000 where id = 'dddddddd-0000-4000-8000-000000000001';
insert into t_ids select 'r1', (public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  '77777777-7777-4777-8777-777777777772', 'r1', 'dddddddd-0000-4000-8000-000000000024', '산', 3, null, 'xai', 'm', 1000) #>> '{run,id}')::uuid;
select lives_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  (select id from t_ids where name = 'r1'), '77777777-7777-4777-8777-777777777771')$$, 'r1 확인');
select is((public.mark_generation_submitted('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'r1'),
  'rejected', null, 'http_400') ->> 'billable')::boolean, false, '명확한 거부 → failed·비계상');
insert into t_ids select 'r2', (public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  '77777777-7777-4777-8777-777777777772', 'r2', 'dddddddd-0000-4000-8000-000000000024', '산', 3, null, 'xai', 'm', 1000) #>> '{run,id}')::uuid;
select lives_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  (select id from t_ids where name = 'r2'), '77777777-7777-4777-8777-777777777771')$$, 'r2 확인');
select is((public.mark_generation_submitted('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'r2'),
  'unknown', null, 'timeout') ->> 'billable')::boolean, true, '응답 불명 → unknown·계상 유지');
insert into t_ids select 'r3', (public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  '77777777-7777-4777-8777-777777777772', 'r3', 'dddddddd-0000-4000-8000-000000000024', '산', 3, null, 'xai', 'm', 1000) #>> '{run,id}')::uuid;
select lives_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012',
  (select id from t_ids where name = 'r3'), '77777777-7777-4777-8777-777777777771')$$, 'r3 확인');
select lives_ok($$select public.mark_generation_submitted('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'r3'), 'running', 'req-3', null)$$, 'r3 running');
insert into t_ids select 'tok3', (public.claim_generation_finalize('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'r3')) ->> 'finalize_token')::uuid;
select isnt((select id from t_ids where name = 'tok3'), null, 'r3 선점');
update public.production_jobs set status = 'review' where id = 'dddddddd-0000-4000-8000-000000000012';  -- 저장 시점 상태 바뀜
select is((public.finish_generation_run('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 'r3'), (select id from t_ids where name = 'tok3'), 'done',
  'dddddddd-0000-4000-8000-000000000032',
  'dddddddd-0000-4000-8000-000000000001/dddddddd-0000-4000-8000-000000000012/dddddddd-0000-4000-8000-000000000032.mp4',
  10, null, null) ->> 'rejected')::boolean, true, '트리거 상태 거부 → rejected');
select is((select status || ':' || error_code || ':' || billable::text from public.generation_runs where id = (select id from t_ids where name = 'r3')),
  'failed:result_rejected:true', '저장 거부 → failed(result_rejected)·계상 유지');

-- 7. 월 경계(KST): 지난달 확인분은 월 합계에서 빠지고 작업 합계에는 남는다
update public.generation_runs set confirmed_at = date_trunc('month', now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul' - interval '1 second'
  where id = (select id from t_ids where name = 'r2');
select is((public._gen_budget('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000012')
  ->> 'monthly_left_krw')::int, 10000 - 3500 - 1000, '지난달(KST) 확인분 제외');

-- 9. 제출 전 중단 고착(리뷰 반영 2): 확인 후 5분 넘게 request_id 없는 confirmed → unknown(계상 유지)
insert into t_ids select 's1', (public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 's1', 'dddddddd-0000-4000-8000-000000000021', '들판', 3, null, 'xai', 'm', 500) #>> '{run,id}')::uuid;
select lives_ok($$select public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 's1'), '77777777-7777-4777-8777-777777777771')$$, 's1 확인');
select is((public.begin_generation_refresh('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 's1')) ->> 'status'), 'confirmed', '5분 안: confirmed 유지');
update public.generation_runs set confirmed_at = now() - interval '6 minutes' where id = (select id from t_ids where name = 's1');
select is((public.confirm_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  (select id from t_ids where name = 's1'), '77777777-7777-4777-8777-777777777771') #>> '{run,status}'),
  'unknown', '재확인: 5분 지난 제출 기록 없음 → unknown');
select is((select error_code || ':' || billable::text from public.generation_runs where id = (select id from t_ids where name = 's1')),
  'submit_stalled:true', '마감 사유·계상 유지');
select throws_ok($$select public.mark_generation_submitted('dddddddd-0000-4000-8000-000000000001', (select id from t_ids where name = 's1'), 'running', 'late', null)$$,
  'NR010', null, '마감 뒤 늦은 제출 기록 거부');

-- 10. 작업 삭제(리뷰 반영 1): run·비용·멱등 키 보존(job_id null), 월 사용액 그대로
create temp table t_before as
  select (public._gen_budget('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011') ->> 'monthly_left_krw')::int as left_krw;
delete from public.production_jobs where id = 'dddddddd-0000-4000-8000-000000000012';
select is((select count(*)::int from public.generation_runs where idempotency_key in ('r1', 'r2', 'r3') and job_id is null), 3,
  '작업 삭제 뒤 run 3건 보존(job_id null)');
select is((public._gen_budget('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011') ->> 'monthly_left_krw')::int,
  (select left_krw from t_before), '작업 삭제 뒤 월 사용액 그대로');
select throws_ok($$select public.quote_generation_run('dddddddd-0000-4000-8000-000000000001', 'dddddddd-0000-4000-8000-000000000011',
  '77777777-7777-4777-8777-777777777772', 'r1', 'dddddddd-0000-4000-8000-000000000021', '바다', 3, null, 'xai', 'm', 100)$$,
  'NR011', null, '삭제된 작업의 멱등 키 재사용 거부');

-- 8. RLS: 구성원은 자기 워크스페이스 run만, 다른 워크스페이스 0건
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"77777777-7777-4777-8777-777777777772","role":"authenticated"}', true);
select is((select count(*)::int from public.generation_runs), 6, '구성원: 자기 워크스페이스 run 6건');
select set_config('request.jwt.claims', '{"sub":"77777777-7777-4777-8777-777777777773","role":"authenticated"}', true);
select is((select count(*)::int from public.generation_runs), 0, '다른 워크스페이스 구성원: 0건');
reset role;

select * from finish();
rollback;
