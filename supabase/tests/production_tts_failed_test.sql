-- task-030 tts_failed(000020) 테스트: W-09 실패 보고 → job review 복귀, A-16 재시도 거부
-- 근거: tasks/task-030.md#착수-결정 I1. 나머지 동작은 production_render_test.sql(000017).
begin;
create extension if not exists pgtap with schema extensions;
select plan(4);

insert into auth.users (id, email, aud, role) values
  ('30303030-3030-4030-8030-303030303030', 'prod-tts@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('dddddddd-0030-4000-8000-000000000001', 'tts-w1');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('dddddddd-0030-4000-8000-0000000000c1', 'dddddddd-0030-4000-8000-000000000001', 'T', 'h');

-- j1: tts_failed로 실패한 작업(재시도 대상), j2: 렌더 중(실패 보고 대상)
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, status, failed_stage,
   error_code, claimed_by, created_at, updated_at) values
  ('dddddddd-0030-4000-8000-000000000011', 'dddddddd-0030-4000-8000-000000000001', 'j1', 60, 'category-1080-v1', 'k1', 'failed', 'audio', 'tts_failed', null, now(), now()),
  ('dddddddd-0030-4000-8000-000000000012', 'dddddddd-0030-4000-8000-000000000001', 'j2', 60, 'category-1080-v1', 'k2', 'rendering', null, null, null, now(), now());
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, spec, approved_at) values
  ('dddddddd-0030-4000-8000-000000000111', 'dddddddd-0030-4000-8000-000000000001', 'dddddddd-0030-4000-8000-000000000011', 1, '{"x": 1}', now()),
  ('dddddddd-0030-4000-8000-000000000112', 'dddddddd-0030-4000-8000-000000000001', 'dddddddd-0030-4000-8000-000000000012', 1, '{"x": 1}', now());
update public.production_jobs j set current_revision_id = r.id
  from public.edit_revisions r where r.job_id = j.id and j.workspace_id = 'dddddddd-0030-4000-8000-000000000001';

insert into public.render_runs (id, workspace_id, job_id, revision_id, idempotency_key, preset_version,
  status, error_stage, error_code, attempt, claimed_by, started_at, created_at) values
  ('dddddddd-0030-4000-8000-000000000211', 'dddddddd-0030-4000-8000-000000000001', 'dddddddd-0030-4000-8000-000000000011',
   'dddddddd-0030-4000-8000-000000000111', 'r1', 'category-1080-v1', 'failed', 'audio', 'tts_failed', 1, null, null, now() - interval '1 hour'),
  ('dddddddd-0030-4000-8000-000000000212', 'dddddddd-0030-4000-8000-000000000001', 'dddddddd-0030-4000-8000-000000000012',
   'dddddddd-0030-4000-8000-000000000112', 'r2', 'category-1080-v1', 'running', null, null, 1,
   'dddddddd-0030-4000-8000-0000000000c1', now(), now());

-- 1. A-16: tts_failed run 거부(편집안에서 첨부 음성으로 바꿔 A-15로 다시 요청)
select throws_ok(
  $$select public.retry_render_run('dddddddd-0030-4000-8000-000000000001', 'dddddddd-0030-4000-8000-000000000011',
    '30303030-3030-4030-8030-303030303030', 'dddddddd-0030-4000-8000-000000000211')$$,
  'NR010', null, 'retry: tts_failed run 거부');
select is((select count(*) from public.render_runs where job_id = 'dddddddd-0030-4000-8000-000000000011'), 1::bigint,
  'retry: 거부 시 새 run 없음');

-- 2. W-09: tts_failed 실패 보고 → job review 복귀(편집안 보존), run에 사유 기록
select is(
  public.finish_production_task('dddddddd-0030-4000-8000-000000000001', 'dddddddd-0030-4000-8000-0000000000c1', 'render',
    'dddddddd-0030-4000-8000-000000000212', 'failed', '{}', null, 'audio', 'tts_failed', null, null)->>'status',
  'failed', 'finish render: tts_failed 실패 보고');
select ok(
  (select j.status = 'review' and j.failed_stage is null and j.error_code is null
     and j.current_revision_id = 'dddddddd-0030-4000-8000-000000000112'
     and r.status = 'failed' and r.error_stage = 'audio' and r.error_code = 'tts_failed'
   from public.production_jobs j join public.render_runs r on r.job_id = j.id
   where j.id = 'dddddddd-0030-4000-8000-000000000012'),
  'finish render: tts_failed → job review 복귀·run failed(tts_failed)');

select * from finish();
rollback;
