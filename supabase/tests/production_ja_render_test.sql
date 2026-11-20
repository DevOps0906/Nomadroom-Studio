-- task-050 일본어판 렌더(000028): request_render_run ja 분기·retry ja 거부·claim ja 능력,
-- ja 요청·완료·실패·만료 후 job 상태 불변. 근거: tasks/task-050.md#착수-결정 K2·K3·K8·K9
begin;
create extension if not exists pgtap with schema extensions;
select plan(24);

insert into auth.users (id, email, aud, role) values
  ('50505050-5050-4050-8050-505050505050', 'prod-ja-render@test.local', 'authenticated', 'authenticated');
insert into public.workspaces (id, name) values
  ('50000000-0000-4000-8000-000000000001', 'prod-ja-render-a');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('50000000-0000-4000-8000-0000000000c1', '50000000-0000-4000-8000-000000000001', 'w-ko', 'h1'),
  ('50000000-0000-4000-8000-0000000000c2', '50000000-0000-4000-8000-000000000001', 'w-ja', 'h2');

-- 21: inspect(ko 승인·ja 승인 파생) · 22: review(같은 구성) · 23: inspect(ja가 옛 ko 파생)
-- 24: inspect(ja 미승인)
insert into public.production_jobs
  (id, workspace_id, title, format, segment_len_sec, preset_version, idempotency_key, status) values
  ('50000000-0000-4000-8000-000000000021', '50000000-0000-4000-8000-000000000001', 'j21', 'category', 60, 'category-1080-v1', 'k21', 'inspect'),
  ('50000000-0000-4000-8000-000000000022', '50000000-0000-4000-8000-000000000001', 'j22', 'category', 60, 'category-1080-v1', 'k22', 'review'),
  ('50000000-0000-4000-8000-000000000023', '50000000-0000-4000-8000-000000000001', 'j23', 'category', 60, 'category-1080-v1', 'k23', 'inspect'),
  ('50000000-0000-4000-8000-000000000024', '50000000-0000-4000-8000-000000000001', 'j24', 'category', 60, 'category-1080-v1', 'k24', 'done');
insert into public.edit_revisions (id, workspace_id, job_id, rev_no, spec, approved_at) values
  ('50000000-0000-4000-8000-000000000041', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000021', 1, '{"lang": "ko"}', now()),
  ('50000000-0000-4000-8000-000000000043', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000022', 1, '{"lang": "ko"}', now()),
  ('50000000-0000-4000-8000-000000000045', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000023', 1, '{"lang": "ko"}', now()),
  ('50000000-0000-4000-8000-000000000046', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000023', 2, '{"lang": "ko"}', now()),
  ('50000000-0000-4000-8000-000000000048', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000024', 1, '{"lang": "ko"}', now());
insert into public.edit_revisions (id, workspace_id, job_id, lang, rev_no, spec, derived_from, approved_at) values
  ('50000000-0000-4000-8000-000000000042', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000021', 'ja', 1, '{"lang": "ja"}', '50000000-0000-4000-8000-000000000041', now()),
  ('50000000-0000-4000-8000-000000000044', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000022', 'ja', 1, '{"lang": "ja"}', '50000000-0000-4000-8000-000000000043', now()),
  ('50000000-0000-4000-8000-000000000047', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000023', 'ja', 1, '{"lang": "ja"}', '50000000-0000-4000-8000-000000000045', now()),
  ('50000000-0000-4000-8000-000000000049', '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000024', 'ja', 1, '{"lang": "ja"}', '50000000-0000-4000-8000-000000000048', null);
update public.production_jobs j set current_revision_id = r.id
  from public.edit_revisions r
  where r.job_id = j.id and r.lang = 'ko'
    and r.rev_no = (select max(x.rev_no) from public.edit_revisions x where x.job_id = j.id and x.lang = 'ko');
update public.production_jobs j set current_ja_revision_id = r.id
  from public.edit_revisions r where r.job_id = j.id and r.lang = 'ja';

-- 1. A-15 ja 거부 조건(K2)
select throws_ok(
  $$select public.request_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000022',
    '50505050-5050-4050-8050-505050505050', '50000000-0000-4000-8000-000000000044', 'ja', 'jr-0')$$,
  'NR010', '현재 상태(review)에서는 할 수 없습니다.', 'ja: job review → NR010');
select throws_ok(
  $$select public.request_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000024',
    '50505050-5050-4050-8050-505050505050', '50000000-0000-4000-8000-000000000049', 'ja', 'jr-0')$$,
  'NR012', null, 'ja: 미승인 ja 리비전 → NR012');
select throws_ok(
  $$select public.request_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000021',
    '50505050-5050-4050-8050-505050505050', '50000000-0000-4000-8000-000000000041', 'ja', 'jr-0')$$,
  'NR012', null, 'ja: ko 리비전을 ja로 요청 → NR012');
select throws_ok(
  $$select public.request_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000023',
    '50505050-5050-4050-8050-505050505050', '50000000-0000-4000-8000-000000000047', 'ja', 'jr-0')$$,
  'NR010', '원본(ko) 편집안이 바뀌었습니다. 일본어판을 다시 만드세요.', 'ja: 원본 ko 바뀜(source_changed) → NR010');
select throws_ok(
  $$select public.request_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000021',
    '50505050-5050-4050-8050-505050505050', '50000000-0000-4000-8000-000000000041', 'ko', 'jr-0')$$,
  'NR010', null, 'ko 분기는 그대로(inspect에서 ko → NR010)');
select is((select count(*)::int from public.render_runs where workspace_id = '50000000-0000-4000-8000-000000000001'),
  0, '거부된 요청은 run 없음');

-- 2. ja 요청 성공 — job 상태 불변
create temp table r1 as select public.request_render_run('50000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000021', '50505050-5050-4050-8050-505050505050',
  '50000000-0000-4000-8000-000000000042', 'ja', 'jr-1') as r;
select is((select r ->> 'lang' || ':' || (r ->> 'status') from r1), 'ja:queued', 'ja run queued');
select is((select status from public.production_jobs where id = '50000000-0000-4000-8000-000000000021'),
  'inspect', 'ja 요청 후 job 상태 불변');
select is((select (public.request_render_run('50000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000021', '50505050-5050-4050-8050-505050505050',
  '50000000-0000-4000-8000-000000000042', 'ja', 'jr-1') ->> 'id') = (select r ->> 'id' from r1)),
  true, '같은 키 재요청은 기존 run');

-- 3. claim(K8): ja 능력 없는 워커는 받지 않는다
select is(public.claim_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c1'),
  null, '2인자 claim: ja run 미배정');
select is(public.claim_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c1', array['shopping']),
  null, 'shopping만 알린 워커: ja run 미배정');
select is(public.claim_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c2', array['shopping', 'ja'])
  ->> 'id', (select r ->> 'id' from r1), 'ja 알린 워커가 수령');
select is(public.claim_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c2')
  ->> 'lang', 'ja', '재시작 복구는 능력 조건 없음');

-- 4. 실패 → job 상태 불변, A-16 재시도 거부(K3)
select is(public.finish_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c2',
  'render', (select (r ->> 'id')::uuid from r1), 'failed', null, null, 'render', 'render_failed', null, null) ->> 'status',
  'failed', 'ja run 실패 보고');
select is((select status || ':' || coalesce(failed_stage, '-') from public.production_jobs
  where id = '50000000-0000-4000-8000-000000000021'), 'inspect:-', 'ja 실패 후 job 상태 불변');
select throws_ok(
  format($$select public.retry_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000021',
    '50505050-5050-4050-8050-505050505050', %L)$$, (select r ->> 'id' from r1)),
  'NR010', '일본어판 렌더는 다시 렌더 요청하세요.', 'A-16 ja → NR010');

-- 5. 실패 뒤 A-15 재요청 → 수령 안 된 채 10분 → 만료, job 상태 불변
update public.render_runs set created_at = now() - interval '2 minutes'
  where workspace_id = '50000000-0000-4000-8000-000000000001';
create temp table r2 as select public.request_render_run('50000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000021', '50505050-5050-4050-8050-505050505050',
  '50000000-0000-4000-8000-000000000042', 'ja', 'jr-2') as r;
select is((select r ->> 'status' from r2), 'queued', '실패 run 뒤 ja 재요청 가능');
update public.render_runs set created_at = now() - interval '11 minutes'
  where id = (select (r ->> 'id')::uuid from r2);
select is((public.expire_production_offline('50000000-0000-4000-8000-000000000001') ->> 'expired')::int, 1, 'queued ja run 만료');
select is((select status || ':' || coalesce(error_code, '-') from public.render_runs
  where id = (select (r ->> 'id')::uuid from r2)), 'failed:worker_offline', 'ja run worker_offline');
select is((select status from public.production_jobs where id = '50000000-0000-4000-8000-000000000021'),
  'inspect', 'ja 만료 후 job 상태 불변');

-- 6. 완료 → job 상태 불변
create temp table r3 as select public.request_render_run('50000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000021', '50505050-5050-4050-8050-505050505050',
  '50000000-0000-4000-8000-000000000042', 'ja', 'jr-3') as r;
select is(public.claim_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c2', array['ja'])
  ->> 'id', (select r ->> 'id' from r3), '두 번째 ja run 수령');
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, created_by, render_run_id)
select ('50000000-0000-4000-8000-0000000003' || n)::uuid, '50000000-0000-4000-8000-000000000001',
       '50000000-0000-4000-8000-000000000021', k,
       '50000000-0000-4000-8000-000000000001/50000000-0000-4000-8000-000000000021/50000000-0000-4000-8000-0000000003' || n || '.' || x,
       m, '50000000-0000-4000-8000-0000000000c2', (select (r ->> 'id')::uuid from r3)
  from (values ('01', 'output_mp4', 'mp4', 'video/mp4'), ('02', 'report', 'json', 'application/json')) v(n, k, x, m);
select is(public.finish_production_task('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-0000000000c2',
  'render', (select (r ->> 'id')::uuid from r3), 'done',
  array['50000000-0000-4000-8000-000000000301', '50000000-0000-4000-8000-000000000302']::uuid[],
  null, null, null, null, null) ->> 'status', 'done', 'ja run 완료');
select is((select status from public.production_jobs where id = '50000000-0000-4000-8000-000000000021'),
  'inspect', 'ja 완료 후 job 상태 불변');
select throws_ok(
  $$select public.request_render_run('50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000021',
    '50505050-5050-4050-8050-505050505050', '50000000-0000-4000-8000-000000000042', 'ja', 'jr-4')$$,
  'NR014', null, '같은 (작업, 리비전, ja) 완료 run → NR014');

select * from finish();
rollback;
