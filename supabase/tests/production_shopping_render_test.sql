-- task-045 쇼핑 렌더러(000024) 테스트: claim은 'shopping'을 알린 워커에게만 쇼핑 prepare·render를
-- 새로 주고, 2인자 claim(구버전 워커)은 계속 보류. 권한은 service_role만.
begin;
create extension if not exists pgtap with schema extensions;
select plan(9);

insert into public.workspaces (id, name) values ('f4500000-0000-4000-8000-000000000001', 'shop-render-a');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('f4500000-0000-4000-8000-0000000000c1', 'f4500000-0000-4000-8000-000000000001', 'w1', 'h1'),
  ('f4500000-0000-4000-8000-0000000000c2', 'f4500000-0000-4000-8000-000000000001', 'w2', 'h2'),
  ('f4500000-0000-4000-8000-0000000000c3', 'f4500000-0000-4000-8000-000000000001', 'w3', 'h3');
-- 15 쇼핑 preparing(가장 오래됨) · 14 일반 preparing
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical, status, created_at) values
  ('f4500000-0000-4000-8000-000000000015', 'f4500000-0000-4000-8000-000000000001', 's', 20, 'shopping-1080-v1', 'b-15',
   'shopping', 'shopping', 'product', 'preparing', now() - interval '1 hour');
insert into public.production_jobs (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, status, created_at) values
  ('f4500000-0000-4000-8000-000000000014', 'f4500000-0000-4000-8000-000000000001', 'g', 60, 'category-1080-v1', 'b-14', 'preparing',
   now() - interval '30 minutes');

select is(public.claim_production_task('f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-0000000000c1') ->> 'job_id',
  'f4500000-0000-4000-8000-000000000014', '2인자 claim: 쇼핑을 건너뛰고 일반 작업');
select is(public.claim_production_task('f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-0000000000c2', '{}'::text[]),
  null, '지원 형식 없음: 쇼핑만 남으면 수령 없음');
select is(public.claim_production_task('f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-0000000000c2', array['shopping']) ->> 'job_kind',
  'shopping', 'shopping을 알린 워커는 쇼핑 prepare 수령');
select is((select claimed_by::text from public.production_jobs where id = 'f4500000-0000-4000-8000-000000000015'),
  'f4500000-0000-4000-8000-0000000000c2', '쇼핑 작업 수령자 기록');
select is(public.claim_production_task('f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-0000000000c2') ->> 'job_id',
  'f4500000-0000-4000-8000-000000000015', '재시작 복구(2인자)는 형식 조건 없이 같은 task');

-- 쇼핑 render queued: 지원 워커만
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical, status) values
  ('f4500000-0000-4000-8000-000000000016', 'f4500000-0000-4000-8000-000000000001', 's', 20, 'shopping-1080-v1', 'b-16',
   'shopping', 'shopping', 'product', 'rendering');
insert into public.edit_revisions (id, workspace_id, job_id, lang, rev_no, spec, approved_at) values
  ('f4500000-0000-4000-8000-000000000061', 'f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-000000000016',
   'ko', 1, '{"cuts": []}', now());
insert into public.render_runs (id, workspace_id, job_id, revision_id, lang, attempt, idempotency_key, preset_version) values
  ('f4500000-0000-4000-8000-000000000071', 'f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-000000000016',
   'f4500000-0000-4000-8000-000000000061', 'ko', 1, 'b-r1', 'shopping-1080-v1');
select is(public.claim_production_task('f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-0000000000c3'),
  null, '2인자 claim: 쇼핑 render도 보류');
select is(public.claim_production_task('f4500000-0000-4000-8000-000000000001', 'f4500000-0000-4000-8000-0000000000c3', array['shopping']) ->> 'id',
  'f4500000-0000-4000-8000-000000000071', 'shopping 워커는 쇼핑 render 수령(spec 포함)');

select ok(
  not has_function_privilege('authenticated', 'public.claim_production_task(uuid, uuid, text[])', 'execute')
  and not has_function_privilege('anon', 'public.claim_production_task(uuid, uuid, text[])', 'execute'),
  '3인자 claim: 브라우저 역할 실행 불가');
select ok(has_function_privilege('service_role', 'public.claim_production_task(uuid, uuid, text[])', 'execute'),
  '3인자 claim: service_role 실행 가능');

select * from finish();
rollback;
