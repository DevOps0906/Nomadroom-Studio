-- task-044 쇼핑 API 보조(000023) 테스트: 원본 계보 FK·트리거, 원본 개수(일반 ready 1·쇼핑 10),
-- ready 전환·삭제 상태 조건, 쇼핑 prepare finish(원본마다 한 벌), claim 쇼핑 보류(045 전).
begin;
create extension if not exists pgtap with schema extensions;
select plan(30);

insert into public.workspaces (id, name) values ('f4400000-0000-4000-8000-000000000001', 'shop-api-a');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('f4400000-0000-4000-8000-0000000000c1', 'f4400000-0000-4000-8000-000000000001', 'w1', 'h1'),
  ('f4400000-0000-4000-8000-0000000000c2', 'f4400000-0000-4000-8000-000000000001', 'w2', 'h2'),
  ('f4400000-0000-4000-8000-0000000000c3', 'f4400000-0000-4000-8000-000000000001', 'w3', 'h3');
-- 작업: 11 일반 draft · 12 쇼핑 draft · 13 쇼핑(finish용) · 14 일반 preparing · 15 쇼핑 preparing(가장 오래됨)
insert into public.production_jobs (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key) values
  ('f4400000-0000-4000-8000-000000000011', 'f4400000-0000-4000-8000-000000000001', 'g', 60, 'category-1080-v1', 'a-11');
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical) values
  ('f4400000-0000-4000-8000-000000000012', 'f4400000-0000-4000-8000-000000000001', 's', 20, 'shopping-1080-v1', 'a-12', 'shopping', 'shopping', 'product'),
  ('f4400000-0000-4000-8000-000000000013', 'f4400000-0000-4000-8000-000000000001', 's', 20, 'shopping-1080-v1', 'a-13', 'shopping', 'shopping', 'travel');

create function pg_temp.asset(p_id text, p_job text, p_kind text, p_status text, p_parent text default null,
                              p_by text default null)
returns void language sql as $$
  insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, status, parent_asset_id, created_by, size_bytes)
  values (p_id::uuid, 'f4400000-0000-4000-8000-000000000001', p_job::uuid, p_kind,
          'f4400000-0000-4000-8000-000000000001/' || p_job || '/' || p_id || '.mp4', 'video/mp4', p_status,
          p_parent::uuid, p_by::uuid, 10);
$$;

-- 1. 계보(P1) ---------------------------------------------------------------
select pg_temp.asset('f4400000-0000-4000-8000-000000000101', 'f4400000-0000-4000-8000-000000000013', 'source_upload', 'ready');
select pg_temp.asset('f4400000-0000-4000-8000-000000000102', 'f4400000-0000-4000-8000-000000000013', 'source_upload', 'ready');
select pg_temp.asset('f4400000-0000-4000-8000-000000000121', 'f4400000-0000-4000-8000-000000000012', 'source_upload', 'pending');
select has_column('public', 'production_assets', 'parent_asset_id', 'parent_asset_id 칼럼');
select throws_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000190', 'f4400000-0000-4000-8000-000000000013', 'source_upload', 'pending',
                         'f4400000-0000-4000-8000-000000000101')$$,
  '23514', null, '원본(source_upload)은 parent를 가질 수 없음');
select throws_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000191', 'f4400000-0000-4000-8000-000000000013', 'source', 'pending',
                         'f4400000-0000-4000-8000-000000000121')$$,
  '23514', null, '다른 작업의 원본을 parent로 거부');
select pg_temp.asset('f4400000-0000-4000-8000-000000000192', 'f4400000-0000-4000-8000-000000000013', 'analysis', 'pending',
                     'f4400000-0000-4000-8000-000000000101', 'f4400000-0000-4000-8000-0000000000c1');
select throws_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000193', 'f4400000-0000-4000-8000-000000000013', 'sheet', 'pending',
                         'f4400000-0000-4000-8000-000000000192')$$,
  '23514', null, 'source_upload가 아닌 자산을 parent로 거부');
delete from public.production_assets where id = 'f4400000-0000-4000-8000-000000000192';

-- 2. 원본 개수(P2) ------------------------------------------------------------
select pg_temp.asset('f4400000-0000-4000-8000-000000000111', 'f4400000-0000-4000-8000-000000000011', 'source_upload', 'ready');
select pg_temp.asset('f4400000-0000-4000-8000-000000000112', 'f4400000-0000-4000-8000-000000000011', 'source_upload', 'pending');
select throws_ok(
  $$update public.production_assets set status = 'ready' where id = 'f4400000-0000-4000-8000-000000000112'$$,
  '23505', null, '일반: 두 번째 ready 원본 거부');
select ok(not exists (select 1 from pg_indexes where indexname = 'production_assets_one_ready_source_uidx'),
  '부분 unique 인덱스는 트리거로 대체');
-- 쇼핑 12: pending 1건(121) + 9건 = 10건, 11건째 거부
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, status)
  select g.id, 'f4400000-0000-4000-8000-000000000001', 'f4400000-0000-4000-8000-000000000012', 'source_upload',
         'f4400000-0000-4000-8000-000000000001/f4400000-0000-4000-8000-000000000012/' || g.id || '.mp4', 'video/mp4', 'pending'
    from (select gen_random_uuid() as id from generate_series(1, 9)) g;
select is((select count(*)::int from public.production_assets
            where job_id = 'f4400000-0000-4000-8000-000000000012' and kind = 'source_upload'), 10, '쇼핑: 원본 10건까지 허용');
select throws_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000129', 'f4400000-0000-4000-8000-000000000012', 'source_upload', 'pending')$$,
  '23505', null, '쇼핑: 11건째(pending 포함) 거부');
select lives_ok(
  $$update public.production_assets set status = 'ready'
      where job_id = 'f4400000-0000-4000-8000-000000000012' and kind = 'source_upload'$$,
  '쇼핑: 여러 원본 ready 허용');
update public.production_assets set status = 'pending' where id = 'f4400000-0000-4000-8000-000000000121';
update public.production_jobs set status = 'review' where id = 'f4400000-0000-4000-8000-000000000012';
select throws_ok(
  $$update public.production_assets set status = 'ready' where id = 'f4400000-0000-4000-8000-000000000121'$$,
  'NR010', null, 'ready 전환은 draft·failed(prepare)에서만');
update public.production_jobs set status = 'failed', failed_stage = 'prepare' where id = 'f4400000-0000-4000-8000-000000000012';
select lives_ok(
  $$update public.production_assets set status = 'ready' where id = 'f4400000-0000-4000-8000-000000000121'$$,
  'failed(prepare)에서는 ready 전환 허용');

-- 3. ready 원본 삭제(P9) ------------------------------------------------------
update public.production_jobs set status = 'preparing', failed_stage = null where id = 'f4400000-0000-4000-8000-000000000012';
select throws_ok(
  $$delete from public.production_assets where id = 'f4400000-0000-4000-8000-000000000121'$$,
  'NR010', null, '준비 중에는 ready 원본 삭제 거부');
update public.production_jobs set status = 'draft' where id = 'f4400000-0000-4000-8000-000000000012';
select lives_ok(
  $$delete from public.production_assets where id = 'f4400000-0000-4000-8000-000000000121'$$,
  'draft에서는 ready 원본 삭제 허용');

-- 4. 쇼핑 prepare finish(P3) --------------------------------------------------
update public.production_jobs set status = 'preparing', claimed_by = 'f4400000-0000-4000-8000-0000000000c1'
  where id = 'f4400000-0000-4000-8000-000000000013';
select pg_temp.asset('f4400000-0000-4000-8000-000000000201', 'f4400000-0000-4000-8000-000000000013', 'source', 'pending',
                     'f4400000-0000-4000-8000-000000000101', 'f4400000-0000-4000-8000-0000000000c1');
select pg_temp.asset('f4400000-0000-4000-8000-000000000202', 'f4400000-0000-4000-8000-000000000013', 'analysis', 'pending',
                     'f4400000-0000-4000-8000-000000000101', 'f4400000-0000-4000-8000-0000000000c1');
select pg_temp.asset('f4400000-0000-4000-8000-000000000203', 'f4400000-0000-4000-8000-000000000013', 'sheet', 'pending',
                     'f4400000-0000-4000-8000-000000000101', 'f4400000-0000-4000-8000-0000000000c1');
select pg_temp.asset('f4400000-0000-4000-8000-000000000211', 'f4400000-0000-4000-8000-000000000013', 'source', 'pending',
                     'f4400000-0000-4000-8000-000000000102', 'f4400000-0000-4000-8000-0000000000c1');
select pg_temp.asset('f4400000-0000-4000-8000-000000000212', 'f4400000-0000-4000-8000-000000000013', 'analysis', 'pending',
                     'f4400000-0000-4000-8000-000000000102', 'f4400000-0000-4000-8000-0000000000c1');
select pg_temp.asset('f4400000-0000-4000-8000-000000000213', 'f4400000-0000-4000-8000-000000000013', 'sheet', 'pending',
                     'f4400000-0000-4000-8000-000000000102', 'f4400000-0000-4000-8000-0000000000c1');
select pg_temp.asset('f4400000-0000-4000-8000-000000000299', 'f4400000-0000-4000-8000-000000000013', 'sheet', 'pending',
                     null, 'f4400000-0000-4000-8000-0000000000c1');

create function pg_temp.finish(p_ids text[]) returns jsonb language sql as $$
  select public.finish_production_task('f4400000-0000-4000-8000-000000000001', 'f4400000-0000-4000-8000-0000000000c1',
    'prepare', 'f4400000-0000-4000-8000-000000000013', 'done', p_ids::uuid[],
    '{"duration_sec": 10, "width": 1080, "height": 1920, "has_audio": true}', null, null, '{}', null);
$$;
select throws_ok(
  $$select pg_temp.finish(array['f4400000-0000-4000-8000-000000000201', 'f4400000-0000-4000-8000-000000000202',
                                'f4400000-0000-4000-8000-000000000203'])$$,
  'NR012', null, '원본 하나만 끝나면 거부(전부 끝나야 review)');
select throws_ok(
  $$select pg_temp.finish(array['f4400000-0000-4000-8000-000000000201', 'f4400000-0000-4000-8000-000000000202',
                                'f4400000-0000-4000-8000-000000000203', 'f4400000-0000-4000-8000-000000000211',
                                'f4400000-0000-4000-8000-000000000212'])$$,
  'NR012', null, '원본별 sheet 없음 거부');
select throws_ok(
  $$select pg_temp.finish(array['f4400000-0000-4000-8000-000000000201', 'f4400000-0000-4000-8000-000000000202',
                                'f4400000-0000-4000-8000-000000000203', 'f4400000-0000-4000-8000-000000000211',
                                'f4400000-0000-4000-8000-000000000212', 'f4400000-0000-4000-8000-000000000213',
                                'f4400000-0000-4000-8000-000000000299'])$$,
  'NR012', null, 'parent 없는 산출물 거부');
select lives_ok(
  $$select pg_temp.finish(array['f4400000-0000-4000-8000-000000000201', 'f4400000-0000-4000-8000-000000000202',
                                'f4400000-0000-4000-8000-000000000203', 'f4400000-0000-4000-8000-000000000211',
                                'f4400000-0000-4000-8000-000000000212', 'f4400000-0000-4000-8000-000000000213'])$$,
  '원본마다 source·analysis·sheet가 있으면 완료');
select is((select status from public.production_jobs where id = 'f4400000-0000-4000-8000-000000000013'), 'review',
  '쇼핑 prepare 완료 → review');
select is((select count(*)::int from public.production_assets where id = 'f4400000-0000-4000-8000-000000000299'), 0,
  '목록 밖 pending 산출물은 정리');

-- 5. claim 쇼핑 보류(P4, task-045 전) ----------------------------------------
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical, status, created_at) values
  ('f4400000-0000-4000-8000-000000000015', 'f4400000-0000-4000-8000-000000000001', 's', 20, 'shopping-1080-v1', 'a-15',
   'shopping', 'shopping', 'product', 'preparing', now() - interval '1 hour');
insert into public.production_jobs (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, status) values
  ('f4400000-0000-4000-8000-000000000014', 'f4400000-0000-4000-8000-000000000001', 'g', 60, 'category-1080-v1', 'a-14', 'preparing');
select is(public.claim_production_task('f4400000-0000-4000-8000-000000000001', 'f4400000-0000-4000-8000-0000000000c2') ->> 'job_id',
  'f4400000-0000-4000-8000-000000000014', 'claim: 더 오래된 쇼핑 작업을 건너뛰고 일반 작업 수령');
select is(public.claim_production_task('f4400000-0000-4000-8000-000000000001', 'f4400000-0000-4000-8000-0000000000c3'),
  null, 'claim: 쇼핑 작업만 남으면 수령 없음');

-- 6. 권한: 트리거 함수는 브라우저 역할 실행 불가
select ok(
  not has_function_privilege('authenticated', 'public.production_assets_source_limit()', 'execute')
  and not has_function_privilege('anon', 'public.production_assets_parent_source()', 'execute')
  and not has_function_privilege('authenticated', 'public.production_assets_source_delete_guard()', 'execute')
  and not has_function_privilege('authenticated', 'public.production_assets_ref_delete_guard()', 'execute')
  and not has_function_privilege('authenticated', 'public.production_jobs_prepare_source()', 'execute'),
  '새 트리거 함수: authenticated·anon 실행 불가');

-- 7. 리뷰 반영 4: 쇼핑 사진 10·녹음 작업 전체 8(pending 포함, job 행 잠금 후 kind별)
insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, status)
  select g.id, 'f4400000-0000-4000-8000-000000000001', 'f4400000-0000-4000-8000-000000000012', g.kind,
         'f4400000-0000-4000-8000-000000000001/f4400000-0000-4000-8000-000000000012/' || g.id || '.png', 'image/png', 'pending'
    from (select gen_random_uuid() as id, case when n <= 10 then 'image' else 'narration' end as kind
            from generate_series(1, 14) n) g;
select throws_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000131', 'f4400000-0000-4000-8000-000000000012', 'image', 'pending')$$,
  '23505', null, '쇼핑: 사진 11건째 거부');
-- task-058: 녹음 상한은 작업 전체 8(ko 4 + ja 4). ko 4건 보유 상태에서 ja 4건 추가 허용, 9건째 거부
select lives_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, status)
      select g.id, 'f4400000-0000-4000-8000-000000000001', 'f4400000-0000-4000-8000-000000000012', 'narration',
             'f4400000-0000-4000-8000-000000000001/f4400000-0000-4000-8000-000000000012/' || g.id || '.m4a', 'audio/mp4', 'pending'
        from (select gen_random_uuid() as id from generate_series(1, 4)) g$$,
  '쇼핑: 녹음 4건 보유 뒤 4건 더(ja) 허용');
select throws_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000132', 'f4400000-0000-4000-8000-000000000012', 'narration', 'pending')$$,
  '23505', null, '쇼핑: 녹음 9건째 거부');
select lives_ok(
  $$select pg_temp.asset('f4400000-0000-4000-8000-000000000133', 'f4400000-0000-4000-8000-000000000011', 'narration', 'pending')$$,
  '일반 작업은 업로드 상한 트리거 대상 아님');

-- 8. 리뷰 반영 3: 업로드 작업이 ready 원본 없이 preparing이 되면 거부
insert into public.production_jobs (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key) values
  ('f4400000-0000-4000-8000-000000000016', 'f4400000-0000-4000-8000-000000000001', 'g', 60, 'category-1080-v1', 'a-16');
select throws_ok(
  $$update public.production_jobs set status = 'preparing' where id = 'f4400000-0000-4000-8000-000000000016'$$,
  'NR010', null, '원본 없는 준비 시작 거부(원본 삭제와 경합 방지)');

-- 9. 리뷰 반영 6: 현재 리비전이 참조하는 image·bgm·narration 삭제 거부
select pg_temp.asset('f4400000-0000-4000-8000-000000000301', 'f4400000-0000-4000-8000-000000000013', 'image', 'ready');
select pg_temp.asset('f4400000-0000-4000-8000-000000000302', 'f4400000-0000-4000-8000-000000000013', 'bgm', 'ready');
update public.edit_revisions
  set spec = '{"cuts": [{"source_asset_id": "f4400000-0000-4000-8000-000000000301"}], "voice": {}}'
  where job_id = 'f4400000-0000-4000-8000-000000000013';
select throws_ok(
  $$delete from public.production_assets where id = 'f4400000-0000-4000-8000-000000000301'$$,
  'NR010', null, '현재 리비전 컷이 쓰는 사진 삭제 거부');
select lives_ok(
  $$delete from public.production_assets where id = 'f4400000-0000-4000-8000-000000000302'$$,
  '참조하지 않는 BGM 삭제 허용');
update public.edit_revisions
  set spec = '{"cuts": [], "bgm_asset_id": "f4400000-0000-4000-8000-000000000301"}'
  where job_id = 'f4400000-0000-4000-8000-000000000013';
select throws_ok(
  $$delete from public.production_assets where id = 'f4400000-0000-4000-8000-000000000301'$$,
  'NR010', null, 'bgm_asset_id로 참조 중이면 거부');

select * from finish();
rollback;
