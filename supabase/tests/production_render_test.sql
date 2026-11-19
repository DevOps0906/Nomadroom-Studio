-- task-023 렌더·제작 워커 RPC(000017) 테스트: 요청·멱등·active 유니크 409·수령(1건)·만료·재시도·완료
-- 근거: tasks/task-023.md#착수-결정 E1~E6·E11. 실제 동시 수령(skip locked)은 로컬 스모크에서 확인.
begin;
create extension if not exists pgtap with schema extensions;
select plan(43);

insert into auth.users (id, email, aud, role) values
  ('66666666-6666-4666-8666-666666666666', 'prod-render@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('eeeeeeee-0000-4000-8000-000000000001', 'render-w1'),
  ('eeeeeeee-0000-4000-8000-000000000002', 'render-w2'),
  ('eeeeeeee-0000-4000-8000-000000000003', 'render-w3'),
  ('eeeeeeee-0000-4000-8000-000000000004', 'render-w4'),
  ('eeeeeeee-0000-4000-8000-000000000005', 'render-w5'),
  ('eeeeeeee-0000-4000-8000-000000000006', 'render-w6'),
  ('eeeeeeee-0000-4000-8000-000000000007', 'render-w7');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('eeeeeeee-0000-4000-8000-0000000000c1', 'eeeeeeee-0000-4000-8000-000000000003', 'A', 'h'),
  ('eeeeeeee-0000-4000-8000-0000000000c2', 'eeeeeeee-0000-4000-8000-000000000003', 'B', 'h'),
  ('eeeeeeee-0000-4000-8000-0000000000c3', 'eeeeeeee-0000-4000-8000-000000000003', 'C', 'h'),
  ('eeeeeeee-0000-4000-8000-0000000000c4', 'eeeeeeee-0000-4000-8000-000000000004', 'D', 'h'),
  ('eeeeeeee-0000-4000-8000-0000000000c5', 'eeeeeeee-0000-4000-8000-000000000007', 'F', 'h');

-- 작업(jNN: 앞자리 = 워크스페이스 번호)
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, status, failed_stage,
   error_code, claimed_by, created_at, updated_at) values
  ('eeeeeeee-0000-4000-8000-000000000011', 'eeeeeeee-0000-4000-8000-000000000001', 'j11', 60, 'category-1080-v1', 'k11', 'review', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000012', 'eeeeeeee-0000-4000-8000-000000000001', 'j12', 60, 'category-1080-v1', 'k12', 'review', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000013', 'eeeeeeee-0000-4000-8000-000000000001', 'j13', 60, 'category-1080-v1', 'k13', 'inspect', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000014', 'eeeeeeee-0000-4000-8000-000000000001', 'j14', 60, 'category-1080-v1', 'k14', 'review', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000021', 'eeeeeeee-0000-4000-8000-000000000002', 'j21', 60, 'category-1080-v1', 'k21', 'review', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000022', 'eeeeeeee-0000-4000-8000-000000000002', 'j22', 60, 'category-1080-v1', 'k22', 'failed', 'render', 'render_failed', null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000031', 'eeeeeeee-0000-4000-8000-000000000003', 'j31', 60, 'category-1080-v1', 'k31', 'preparing', null, null, null, now() - interval '1 hour', now()),
  ('eeeeeeee-0000-4000-8000-000000000032', 'eeeeeeee-0000-4000-8000-000000000003', 'j32', 60, 'category-1080-v1', 'k32', 'rendering', null, null, null, now() - interval '2 hours', now()),
  ('eeeeeeee-0000-4000-8000-000000000041', 'eeeeeeee-0000-4000-8000-000000000004', 'j41', 60, 'category-1080-v1', 'k41', 'rendering', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000043', 'eeeeeeee-0000-4000-8000-000000000004', 'j43', 60, 'category-1080-v1', 'k43', 'preparing', null, null, 'eeeeeeee-0000-4000-8000-0000000000c4', now(), now() - interval '4 minutes'),
  ('eeeeeeee-0000-4000-8000-000000000044', 'eeeeeeee-0000-4000-8000-000000000004', 'j44', 60, 'category-1080-v1', 'k44', 'preparing', null, null, 'eeeeeeee-0000-4000-8000-0000000000c4', now(), now() - interval '1 minute'),
  ('eeeeeeee-0000-4000-8000-000000000051', 'eeeeeeee-0000-4000-8000-000000000005', 'j51', 60, 'category-1080-v1', 'k51', 'failed', 'render', 'render_failed', null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000052', 'eeeeeeee-0000-4000-8000-000000000005', 'j52', 60, 'category-1080-v1', 'k52', 'failed', 'render', 'render_failed', null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000053', 'eeeeeeee-0000-4000-8000-000000000005', 'j53', 60, 'category-1080-v1', 'k53', 'failed', 'audio', 'hook_too_long', null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000054', 'eeeeeeee-0000-4000-8000-000000000005', 'j54', 60, 'category-1080-v1', 'k54', 'failed', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000073', 'eeeeeeee-0000-4000-8000-000000000007', 'j73', 60, 'category-1080-v1', 'k73', 'preparing', null, null, 'eeeeeeee-0000-4000-8000-0000000000c5', now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000074', 'eeeeeeee-0000-4000-8000-000000000007', 'j74', 60, 'category-1080-v1', 'k74', 'preparing', null, null, 'eeeeeeee-0000-4000-8000-0000000000c5', now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000061', 'eeeeeeee-0000-4000-8000-000000000006', 'j61', 60, 'category-1080-v1', 'k61', 'rendering', null, null, null, now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000071', 'eeeeeeee-0000-4000-8000-000000000007', 'j71', 60, 'category-1080-v1', 'k71', 'preparing', null, null, 'eeeeeeee-0000-4000-8000-0000000000c5', now(), now()),
  ('eeeeeeee-0000-4000-8000-000000000072', 'eeeeeeee-0000-4000-8000-000000000007', 'j72', 60, 'category-1080-v1', 'k72', 'rendering', null, null, null, now(), now());

-- 리비전(rNN = 작업 jNN의 rev1). r14만 미승인
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, spec, approved_at)
select ('eeeeeeee-0000-4000-8000-0000000001' || right(j.id::text, 2))::uuid, j.workspace_id, j.id, 1,
       '{"x": 1}', case when j.title = 'j14' then null else now() end
from public.production_jobs j
where j.workspace_id::text like 'eeeeeeee-%' and j.title not in ('j31', 'j43', 'j44', 'j71', 'j73', 'j74');
update public.production_jobs j set current_revision_id = r.id
  from public.edit_revisions r where r.job_id = j.id and j.workspace_id::text like 'eeeeeeee-%';

-- 1. A-15 요청·멱등·409(E1·E8)
select is(
  public.request_render_run('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000111', 'ko', 'a')->>'created',
  'true', 'request: 새 run 생성');
select is((select status from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000011'),
  'rendering', 'request: review → rendering');
select is(
  (select r.status || ':' || r.attempt from public.render_runs r where r.idempotency_key = 'a'
     and r.workspace_id = 'eeeeeeee-0000-4000-8000-000000000001'),
  'queued:1', 'request: queued·attempt 1');
select is(
  public.request_render_run('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000111', 'ko', 'a')->>'created',
  'false', 'request: 같은 키 재요청은 기존 run(상태 무관)');
select throws_ok(
  $$select public.request_render_run('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000012',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000112', 'ko', 'a')$$,
  'NR011', null, 'request: 다른 작업의 키 NR011');
select throws_ok(
  $$select public.request_render_run('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000012',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000112', 'ko', 'b')$$,
  'NR014', null, 'request: 워크스페이스 동시 렌더 2건째 NR014(409)');
select throws_ok(
  $$select public.request_render_run('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000013',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000113', 'ko', 'c')$$,
  'NR010', '현재 상태(inspect)에서는 할 수 없습니다.', 'request: review 아님 NR010(현재 상태)');
select throws_ok(
  $$select public.request_render_run('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000014',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000114', 'ko', 'd')$$,
  'NR012', null, 'request: 미승인 리비전 NR012');
select throws_ok(
  $$select public.request_render_run('eeeeeeee-0000-4000-8000-000000000002', 'eeeeeeee-0000-4000-8000-000000000011',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000111', 'ko', 'e')$$,
  'NR009', null, 'request: 다른 워크스페이스 NR009');
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, idempotency_key, preset_version)
    values ('eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000012',
            'eeeeeeee-0000-4000-8000-000000000112', 'direct', 'category-1080-v1')$$,
  '23505', null, 'active 부분 unique: 워크스페이스 두 번째 queued run 거부');
select ok(exists (select 1 from pg_constraint where conname = 'render_runs_workspace_id_idempotency_key_key'),
  'run 멱등 unique 제약 이름(RPC가 찾는 이름)');

-- 1-2. 60초 내 새 키 429(NR013): j22의 실패 run이 방금 만들어졌다
insert into public.render_runs (workspace_id, job_id, revision_id, idempotency_key, preset_version, status)
values ('eeeeeeee-0000-4000-8000-000000000002', 'eeeeeeee-0000-4000-8000-000000000022',
        'eeeeeeee-0000-4000-8000-000000000122', 'old', 'category-1080-v1', 'failed');
select throws_ok(
  $$select public.request_render_run('eeeeeeee-0000-4000-8000-000000000002', 'eeeeeeee-0000-4000-8000-000000000021',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000121', 'ko', 'new')$$,
  'NR013', null, 'request: 60초 내 새 키 NR013(429)');

-- 2. W-05 수령(E2): 가장 오래된 1건, 워커당 1건, 재시작 복구
insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version, created_at)
values ('eeeeeeee-0000-4000-8000-000000000232', 'eeeeeeee-0000-4000-8000-000000000003',
        'eeeeeeee-0000-4000-8000-000000000032', 'eeeeeeee-0000-4000-8000-000000000132', 'q32',
        'category-1080-v1', now() - interval '5 minutes');
select is(
  public.claim_production_task('eeeeeeee-0000-4000-8000-000000000003', 'eeeeeeee-0000-4000-8000-0000000000c1')->>'id',
  'eeeeeeee-0000-4000-8000-000000000031', 'claim: 워커 A는 더 오래된 prepare');
select is(
  public.claim_production_task('eeeeeeee-0000-4000-8000-000000000003', 'eeeeeeee-0000-4000-8000-0000000000c2')
    - 'source_start_sec' - 'segment_len_sec' - 'source_kind',
  jsonb_build_object('kind', 'render', 'id', 'eeeeeeee-0000-4000-8000-000000000232',
    'job_id', 'eeeeeeee-0000-4000-8000-000000000032', 'job_kind', 'general', 'format', 'category',
    'preset_version', 'category-1080-v1', 'lang', 'ko', 'spec', '{"x": 1}'::jsonb),
  'claim: 워커 B는 남은 render(승인 spec 포함)');
select is(
  public.claim_production_task('eeeeeeee-0000-4000-8000-000000000003', 'eeeeeeee-0000-4000-8000-0000000000c3'),
  null, 'claim: 세 번째 워커는 수령할 것 없음(1건만 수령)');
update public.production_jobs set updated_at = now() - interval '2 minutes' where id = 'eeeeeeee-0000-4000-8000-000000000031';
select is(
  public.claim_production_task('eeeeeeee-0000-4000-8000-000000000003', 'eeeeeeee-0000-4000-8000-0000000000c1')->>'id',
  'eeeeeeee-0000-4000-8000-000000000031', 'claim: 재시작 복구는 자기 task');
select is((select updated_at from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000031'), now(),
  'claim: 복구 수령도 updated_at=now(리뷰 반영 3)');
select ok(
  (select status = 'running' and claimed_by = 'eeeeeeee-0000-4000-8000-0000000000c2' and started_at is not null
   from public.render_runs where id = 'eeeeeeee-0000-4000-8000-000000000232'),
  'claim: run running·claimed_by·started_at');
select is((select claimed_by from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000031'),
  'eeeeeeee-0000-4000-8000-0000000000c1'::uuid, 'claim: prepare job claimed_by');

-- 3. 만료(E3)
insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version,
  status, claimed_by, started_at, updated_at)
values ('eeeeeeee-0000-4000-8000-000000000241', 'eeeeeeee-0000-4000-8000-000000000004',
        'eeeeeeee-0000-4000-8000-000000000041', 'eeeeeeee-0000-4000-8000-000000000141', 'r41',
        'category-1080-v1', 'running', 'eeeeeeee-0000-4000-8000-0000000000c4',
        now() - interval '10 minutes', now() - interval '4 minutes');
insert into public.render_runs (workspace_id, job_id, revision_id, idempotency_key, preset_version, created_at)
values ('eeeeeeee-0000-4000-8000-000000000006', 'eeeeeeee-0000-4000-8000-000000000061',
        'eeeeeeee-0000-4000-8000-000000000161', 'q61', 'category-1080-v1', now() - interval '11 minutes');
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, created_by, render_run_id) values
  ('eeeeeeee-0000-4000-8000-000000000341', 'eeeeeeee-0000-4000-8000-000000000004', 'eeeeeeee-0000-4000-8000-000000000041', 'output_mp4',
   'eeeeeeee-0000-4000-8000-000000000004/eeeeeeee-0000-4000-8000-000000000041/eeeeeeee-0000-4000-8000-000000000341.mp4', 'video/mp4', 'eeeeeeee-0000-4000-8000-0000000000c4', 'eeeeeeee-0000-4000-8000-000000000241'),
  ('eeeeeeee-0000-4000-8000-000000000342', 'eeeeeeee-0000-4000-8000-000000000004', 'eeeeeeee-0000-4000-8000-000000000041', 'source',
   'eeeeeeee-0000-4000-8000-000000000004/eeeeeeee-0000-4000-8000-000000000041/eeeeeeee-0000-4000-8000-000000000342.mp4', 'video/mp4', null, null);
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, created_by) values
  ('eeeeeeee-0000-4000-8000-000000000343', 'eeeeeeee-0000-4000-8000-000000000004', 'eeeeeeee-0000-4000-8000-000000000043', 'sheet',
   'eeeeeeee-0000-4000-8000-000000000004/eeeeeeee-0000-4000-8000-000000000043/eeeeeeee-0000-4000-8000-000000000343.jpg', 'image/jpeg', 'eeeeeeee-0000-4000-8000-0000000000c4');
update public.production_assets set status = 'ready' where id = 'eeeeeeee-0000-4000-8000-000000000342';
create temp table expired_w4 as select public.expire_production_offline('eeeeeeee-0000-4000-8000-000000000004') as r;
select is((select (r->>'expired')::int from expired_w4), 2, 'expire: running run 1 + preparing job 1');
select is((select r->'deleted_paths' from expired_w4),
  '["eeeeeeee-0000-4000-8000-000000000004/eeeeeeee-0000-4000-8000-000000000041/eeeeeeee-0000-4000-8000-000000000341.mp4", "eeeeeeee-0000-4000-8000-000000000004/eeeeeeee-0000-4000-8000-000000000043/eeeeeeee-0000-4000-8000-000000000343.jpg"]'::jsonb,
  'expire: 만료 task의 pending 산출물 삭제·경로 반환(리뷰 반영 4)');
select ok(not exists (select 1 from public.production_assets where id in ('eeeeeeee-0000-4000-8000-000000000341', 'eeeeeeee-0000-4000-8000-000000000343'))
  and exists (select 1 from public.production_assets where id = 'eeeeeeee-0000-4000-8000-000000000342'),
  'expire: pending 행만 지우고 ready 입력은 유지');
select is((select status || ':' || error_stage || ':' || error_code from public.render_runs
  where id = 'eeeeeeee-0000-4000-8000-000000000241'), 'failed:render:worker_offline', 'expire: run worker_offline');
select is((select status || ':' || failed_stage || ':' || error_code from public.production_jobs
  where id = 'eeeeeeee-0000-4000-8000-000000000041'), 'failed:render:worker_offline', 'expire: ko job failed(render)');
select is((select status || ':' || failed_stage from public.production_jobs
  where id = 'eeeeeeee-0000-4000-8000-000000000043'), 'failed:prepare', 'expire: 3분 넘은 preparing → failed(prepare)');
select is((select status from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000044'),
  'preparing', 'expire: 1분 전 진행 보고는 유지');
select is((public.expire_production_offline('eeeeeeee-0000-4000-8000-000000000006')->>'expired')::int, 1,
  'expire: 10분 넘게 수령 안 된 queued run → failed(잠금 해제)');

-- 4. A-16 재시도(E5)
insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version,
  status, error_stage, error_code, attempt, created_at) values
  ('eeeeeeee-0000-4000-8000-000000000251', 'eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000051',
   'eeeeeeee-0000-4000-8000-000000000151', 'x51', 'category-1080-v1', 'failed', 'render', 'render_failed', 1, now() - interval '1 hour'),
  ('eeeeeeee-0000-4000-8000-000000000252', 'eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000052',
   'eeeeeeee-0000-4000-8000-000000000152', 'x52', 'category-1080-v1', 'failed', 'render', 'render_failed', 3, now() - interval '1 hour'),
  ('eeeeeeee-0000-4000-8000-000000000253', 'eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000053',
   'eeeeeeee-0000-4000-8000-000000000153', 'x53', 'category-1080-v1', 'failed', 'audio', 'hook_too_long', 1, now() - interval '1 hour');
select throws_ok(
  $$select public.retry_render_run('eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000052',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000252')$$,
  'NR015', null, 'retry: attempt 3 다음은 상한 초과 NR015');
select throws_ok(
  $$select public.retry_render_run('eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000053',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000253')$$,
  'NR010', null, 'retry: hook_too_long run 거부');
select is(
  public.retry_render_run('eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000051',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000251')
    - 'id' - 'job_id' - 'revision_id' - 'preset_version',
  '{"lang": "ko", "status": "queued", "attempt": 2, "retry_of": "eeeeeeee-0000-4000-8000-000000000251", "created": true}'::jsonb,
  'retry: 새 run attempt 2·retry_of');
select throws_ok(
  $$select public.retry_render_run('eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000051',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000251')$$,
  'NR010', null, 'retry: 같은 run 두 번째(job rendering) NR010');

insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version,
  status, attempt, created_at)
values ('eeeeeeee-0000-4000-8000-000000000254', 'eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000054', 'eeeeeeee-0000-4000-8000-000000000154', 'x54',
        'category-1080-v1', 'failed', 1, now() - interval '1 hour');
select throws_ok(
  $$select public.retry_render_run('eeeeeeee-0000-4000-8000-000000000005', 'eeeeeeee-0000-4000-8000-000000000054',
    '66666666-6666-4666-8666-666666666666', 'eeeeeeee-0000-4000-8000-000000000254')$$,
  'NR010', null, 'retry: error_code·failed_stage null도 거부(리뷰 반영 6)');

-- 5. W-09 완료·실패(E6)
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, created_by) values
  ('eeeeeeee-0000-4000-8000-000000000371', 'eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-000000000071', 'source',
   'eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-000000000071/eeeeeeee-0000-4000-8000-000000000371.mp4', 'video/mp4', 'eeeeeeee-0000-4000-8000-0000000000c5'),
  ('eeeeeeee-0000-4000-8000-000000000372', 'eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-000000000071', 'analysis',
   'eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-000000000071/eeeeeeee-0000-4000-8000-000000000372.json', 'application/json', 'eeeeeeee-0000-4000-8000-0000000000c5'),
  ('eeeeeeee-0000-4000-8000-000000000373', 'eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-000000000071', 'sheet',
   'eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-000000000071/eeeeeeee-0000-4000-8000-000000000373.jpg', 'image/jpeg', 'eeeeeeee-0000-4000-8000-0000000000c5'),
  ('eeeeeeee-0000-4000-8000-000000000374', 'eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-000000000071', 'sheet',
   'eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-000000000071/eeeeeeee-0000-4000-8000-000000000374.jpg', 'image/jpeg', 'eeeeeeee-0000-4000-8000-0000000000c5');
select is(
  public.finish_production_task('eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-0000000000c5', 'prepare',
    'eeeeeeee-0000-4000-8000-000000000071', 'done',
    array['eeeeeeee-0000-4000-8000-000000000371', 'eeeeeeee-0000-4000-8000-000000000372', 'eeeeeeee-0000-4000-8000-000000000373']::uuid[],
    '{"duration_sec": 60}', null, null, '{}', '{"errors": [{"code": "schema.missing"}], "warnings": []}')->'deleted_paths',
  '["eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-000000000071/eeeeeeee-0000-4000-8000-000000000374.jpg"]'::jsonb,
  'finish prepare: 목록 밖 pending 삭제 경로 반환');
select ok(
  (select j.status = 'review' and r.rev_no = 1 and j.source_meta->>'duration_sec' = '60'
   from public.production_jobs j join public.edit_revisions r on r.id = j.current_revision_id
   where j.id = 'eeeeeeee-0000-4000-8000-000000000071'),
  'finish prepare: preparing → review + 첫 리비전');
select is((select count(*)::int from public.production_assets
  where job_id = 'eeeeeeee-0000-4000-8000-000000000071' and status = 'ready'), 3, 'finish prepare: 자산 3건 ready');
select throws_ok(
  $$select public.finish_production_task('eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-0000000000c5', 'prepare',
    'eeeeeeee-0000-4000-8000-000000000071', 'failed', '{}', null, 'prepare', 'unknown', null, null)$$,
  'NR010', null, 'finish: 이미 종료 NR010');

insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, created_by)
select ('eeeeeeee-0000-4000-8000-000000000' || n)::uuid, 'eeeeeeee-0000-4000-8000-000000000007', ('eeeeeeee-0000-4000-8000-0000000000' || left(n, 2))::uuid, k,
       'eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-0000000000' || left(n, 2) || '/eeeeeeee-0000-4000-8000-000000000' || n || '.' || x, m, 'eeeeeeee-0000-4000-8000-0000000000c5'
from (values ('731', 'source', 'mp4', 'video/mp4'), ('732', 'source', 'mp4', 'video/mp4'),
             ('733', 'analysis', 'json', 'application/json'), ('734', 'sheet', 'jpg', 'image/jpeg'),
             ('741', 'source', 'mp4', 'video/mp4'), ('742', 'analysis', 'json', 'application/json'),
             ('743', 'sheet', 'jpg', 'image/jpeg')) v(n, k, x, m);
select throws_ok(
  $$select public.finish_production_task('eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-0000000000c5', 'prepare',
    'eeeeeeee-0000-4000-8000-000000000073', 'done',
    array['eeeeeeee-0000-4000-8000-000000000731', 'eeeeeeee-0000-4000-8000-000000000732', 'eeeeeeee-0000-4000-8000-000000000733', 'eeeeeeee-0000-4000-8000-000000000734']::uuid[],
    '{}', null, null, '{}', null)$$,
  'NR012', null, 'finish prepare: source 2건 NR012(리뷰 반영 1)');
update public.production_jobs set source_meta = '{"duration_sec": 5}' where id = 'eeeeeeee-0000-4000-8000-000000000074';
select is(
  public.finish_production_task('eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-0000000000c5', 'prepare', 'eeeeeeee-0000-4000-8000-000000000074', 'done',
    array['eeeeeeee-0000-4000-8000-000000000741', 'eeeeeeee-0000-4000-8000-000000000742', 'eeeeeeee-0000-4000-8000-000000000743']::uuid[], null, null, null, '{}', null)->>'status',
  'done', 'finish prepare: meta 없이 완료(API는 400, SQL은 보존)');
select is((select source_meta->>'duration_sec' from public.production_jobs where id = 'eeeeeeee-0000-4000-8000-000000000074'), '5',
  'finish prepare: coalesce(p_meta, source_meta)(리뷰 반영 2)');

insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version,
  status, claimed_by, started_at)
values ('eeeeeeee-0000-4000-8000-000000000272', 'eeeeeeee-0000-4000-8000-000000000007',
        'eeeeeeee-0000-4000-8000-000000000072', 'eeeeeeee-0000-4000-8000-000000000172', 'r72',
        'category-1080-v1', 'running', 'eeeeeeee-0000-4000-8000-0000000000c5', now());
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, created_by, render_run_id) values
  ('eeeeeeee-0000-4000-8000-000000000381', 'eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-000000000072', 'output_mp4',
   'eeeeeeee-0000-4000-8000-000000000007/eeeeeeee-0000-4000-8000-000000000072/eeeeeeee-0000-4000-8000-000000000381.mp4', 'video/mp4',
   'eeeeeeee-0000-4000-8000-0000000000c5', 'eeeeeeee-0000-4000-8000-000000000272');
select throws_ok(
  $$select public.finish_production_task('eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-0000000000c5', 'render',
    'eeeeeeee-0000-4000-8000-000000000272', 'done', array['eeeeeeee-0000-4000-8000-000000000381']::uuid[], null, null, null, null, null)$$,
  'NR012', null, 'finish render: report 없으면 NR012');
select is(
  public.finish_production_task('eeeeeeee-0000-4000-8000-000000000007', 'eeeeeeee-0000-4000-8000-0000000000c5', 'render',
    'eeeeeeee-0000-4000-8000-000000000272', 'failed', '{}', null, 'audio', 'hook_too_long', null, null)->>'status',
  'failed', 'finish render: hook_too_long 실패 보고');
select ok(
  (select j.status = 'review' and j.failed_stage is null and r.status = 'failed' and r.error_code = 'hook_too_long'
     and not exists (select 1 from public.production_assets a where a.id = 'eeeeeeee-0000-4000-8000-000000000381')
   from public.production_jobs j join public.render_runs r on r.job_id = j.id
   where j.id = 'eeeeeeee-0000-4000-8000-000000000072'),
  'finish render: job review 복귀·run failed·pending 산출물 삭제');

-- 6. 권한: service_role만 실행
select ok(
  not has_function_privilege('authenticated', 'public.claim_production_task(uuid, uuid)', 'execute')
  and not has_function_privilege('anon', 'public.request_render_run(uuid, uuid, uuid, uuid, text, text)', 'execute')
  and not has_function_privilege('authenticated', 'public.expire_production_offline(uuid)', 'execute')
  and not has_function_privilege('authenticated', 'public.retry_render_run(uuid, uuid, uuid, uuid)', 'execute')
  and not has_function_privilege('authenticated',
    'public.finish_production_task(uuid, uuid, text, uuid, text, uuid[], jsonb, text, text, jsonb, jsonb)', 'execute'),
  '브라우저 역할은 RPC 실행 불가');

select * from finish();
rollback;
