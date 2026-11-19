-- task-042 쇼핑·일본어판 스키마 테스트 (supabase test db)
-- kind·format·vertical·brief 정합, kind 변경 거부, affiliates 형태, 후보 복합 FK, ja 리비전·파생,
-- render_runs (revision, job, lang) FK, 자산 kind·rights, Storage 버킷·정책, claim job_kind.
begin;
create extension if not exists pgtap with schema extensions;
select plan(60);

-- 픽스처: 워크스페이스 A·B, 후보 A·B, 일반 작업 1·쇼핑 작업 1(A), 워커(A)
insert into public.workspaces (id, name) values
  ('f4200000-0000-4000-8000-000000000001', 'shop-ws-a'),
  ('f4200000-0000-4000-8000-000000000002', 'shop-ws-b');
insert into public.candidates (id, workspace_id, video_id, title) values
  ('f4200000-0000-4000-8000-0000000000a1', 'f4200000-0000-4000-8000-000000000001', 'shop-v-a', 'cand-a'),
  ('f4200000-0000-4000-8000-0000000000b1', 'f4200000-0000-4000-8000-000000000002', 'shop-v-b', 'cand-b');
insert into public.workers (id, workspace_id, name, token_hash) values
  ('f4200000-0000-4000-8000-0000000000c1', 'f4200000-0000-4000-8000-000000000001', 'shop-w', 'h');
insert into public.production_jobs (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key) values
  ('f4200000-0000-4000-8000-000000000011', 'f4200000-0000-4000-8000-000000000001', 'gen-1', 60, 'category-v1', 'sj-1');
insert into public.production_jobs
  (id, workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical, brief, affiliates, comment_keyword)
values
  ('f4200000-0000-4000-8000-000000000012', 'f4200000-0000-4000-8000-000000000001', 'shop-1', 20, 'shopping-v1', 'sj-2',
   'shopping', 'shopping', 'product', '{"product":"x","target":{"gender":"f"}}',
   '[{"lang":"ko","partner":"쿠팡","url":"https://link.coupang.com/a/1"},{"lang":"ja","partner":"楽天","url":"https://a.r10.to/x"}]',
   '링크');

-- 1. 기존·기본값
select is((select kind || '/' || format || '/' || affiliates::text from public.production_jobs
            where id = 'f4200000-0000-4000-8000-000000000011'),
  'general/category/[]', '기본값: kind general · format category · affiliates []');
select is((select vertical from public.production_jobs where id = 'f4200000-0000-4000-8000-000000000012'),
  'product', '쇼핑 작업(shopping·shopping·product·brief·affiliates 2건) 생성');

-- 2. kind·format·vertical·brief 정합
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical)
    values ('f4200000-0000-4000-8000-000000000001', 'x', 20, 'p', 'sj-x1', 'shopping', 'category', 'product')$$,
  '23514', null, 'kind shopping + format category 거부');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, format)
    values ('f4200000-0000-4000-8000-000000000001', 'x', 20, 'p', 'sj-x2', 'shopping')$$,
  '23514', null, 'kind general + format shopping 거부');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format)
    values ('f4200000-0000-4000-8000-000000000001', 'x', 20, 'p', 'sj-x3', 'shopping', 'shopping')$$,
  '23514', null, '쇼핑인데 vertical 없음 거부');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, vertical)
    values ('f4200000-0000-4000-8000-000000000001', 'x', 20, 'p', 'sj-x4', 'travel')$$,
  '23514', null, '일반인데 vertical 있음 거부');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical)
    values ('f4200000-0000-4000-8000-000000000001', 'x', 20, 'p', 'sj-x5', 'shopping', 'shopping', 'food')$$,
  '23514', null, 'vertical 허용 외 값 거부');
select throws_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, brief)
    values ('f4200000-0000-4000-8000-000000000001', 'x', 20, 'p', 'sj-x6', '{"product":"x"}')$$,
  '23514', null, '일반 작업 brief 거부');
select throws_ok(
  $$update public.production_jobs set brief = '["x"]' where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'brief 객체 아님 거부');
select lives_ok(
  $$insert into public.production_jobs (workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical)
    values ('f4200000-0000-4000-8000-000000000001', 'travel', 20, 'p', 'sj-x7', 'shopping', 'shopping', 'travel')$$,
  '여행 쇼핑 작업(brief null) 허용');

-- 3. kind 변경 거부(트리거), 다른 칼럼 수정은 허용
select throws_ok(
  $$update public.production_jobs set kind = 'shopping', format = 'shopping', vertical = 'product'
    where id = 'f4200000-0000-4000-8000-000000000011'$$,
  '23514', 'production_jobs.kind is immutable', 'general → shopping 변경 거부');
select throws_ok(
  $$update public.production_jobs set kind = 'general' where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', 'production_jobs.kind is immutable', 'shopping → general 변경 거부');
select lives_ok(
  $$update public.production_jobs set kind = 'shopping', comment_keyword = '정보' where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '같은 kind 값 update·다른 칼럼 수정 허용');

-- 4. affiliates 형태
select throws_ok(
  $$update public.production_jobs set affiliates = '[{"lang":"ko","partner":"p","url":"http://x.com"}]'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates url http:// 거부(https만)');
select throws_ok(
  $$update public.production_jobs set affiliates = '{"lang":"ko","partner":"p","url":"https://x.com"}'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates 배열 아님 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = '[{"lang":"en","partner":"p","url":"https://x.com"}]'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates lang 허용 외(en) 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = '[{"lang":"ko","partner":" ","url":"https://x.com"}]'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates partner 빈 값 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = '["https://x.com"]' where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates 원소 객체 아님 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = null where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23502', null, 'affiliates null 거부(not null)');
select throws_ok(
  $$update public.production_jobs set affiliates = '[{"lang":"ko","partner":"p","url":"https://x.com/a b"}]'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates url 공백 포함 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = jsonb_build_array(jsonb_build_object(
      'lang', 'ko', 'partner', 'p', 'url', 'https://x.com/' || chr(10) || 'y'))
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates url 제어 문자(개행) 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = jsonb_build_array(jsonb_build_object(
      'lang', 'ko', 'partner', 'p', 'url', 'https://x.com/' || repeat('a', 2040)))
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates url 2048자 초과 거부');
select throws_ok(
  $$update public.production_jobs set affiliates = (select jsonb_agg(jsonb_build_object(
      'lang', 'ko', 'partner', 'p', 'url', 'https://x.com/' || i)) from generate_series(1, 21) i)
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'affiliates 21건 거부(상한 20)');
select lives_ok(
  $$update public.production_jobs set affiliates = (select jsonb_agg(jsonb_build_object(
      'lang', 'ja', 'partner', 'p', 'url', 'https://x.com/' || i)) from generate_series(1, 20) i)
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  'affiliates 20건 허용');

-- 4-1. 크기 상한(brief 32KB)
select throws_ok(
  $$update public.production_jobs set brief = jsonb_build_object('facts',
      (select string_agg(md5(i::text), '') from generate_series(1, 1300) i))
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', null, 'brief 32768바이트 초과 거부');

-- 4-2. service_role 쓰기 경로에서 affiliates check 통과(check 함수 실행 권한)
set local role service_role;
select lives_ok(
  $$insert into public.production_jobs
      (workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical, affiliates)
    values ('f4200000-0000-4000-8000-000000000001', 'sr', 20, 'p', 'sj-sr', 'shopping', 'shopping', 'product',
            '[{"lang":"ko","partner":"쿠팡","url":"https://link.coupang.com/a/2"}]')$$,
  'service_role: affiliates 있는 쇼핑 작업 insert 허용');
select throws_ok(
  $$insert into public.production_jobs
      (workspace_id, title, segment_len_sec, preset_version, idempotency_key, kind, format, vertical, affiliates)
    values ('f4200000-0000-4000-8000-000000000001', 'sr2', 20, 'p', 'sj-sr2', 'shopping', 'shopping', 'product',
            '[{"lang":"ko","partner":"p","url":"http://x.com"}]')$$,
  '23514', null, 'service_role: affiliates http 거부');
reset role;

-- 5. 후보 복합 FK(타 워크스페이스 거부, 삭제 시 candidate_id만 null)
select throws_ok(
  $$update public.production_jobs set candidate_id = 'f4200000-0000-4000-8000-0000000000b1'
    where id = 'f4200000-0000-4000-8000-000000000011'$$,
  '23503', null, '다른 워크스페이스 후보 참조 거부');
select lives_ok(
  $$update public.production_jobs set candidate_id = 'f4200000-0000-4000-8000-0000000000a1'
    where id = 'f4200000-0000-4000-8000-000000000011'$$,
  '같은 워크스페이스 후보 참조 허용');
delete from public.candidates where id = 'f4200000-0000-4000-8000-0000000000a1';
select is((select workspace_id::text || '/' || coalesce(candidate_id::text, 'null') from public.production_jobs
            where id = 'f4200000-0000-4000-8000-000000000011'),
  'f4200000-0000-4000-8000-000000000001/null', '후보 삭제 → candidate_id만 null, workspace_id 유지');

-- 6. 리비전 언어·파생
insert into public.edit_revisions (id, workspace_id, job_id, rev_no) values
  ('f4200000-0000-4000-8000-000000000031', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 1),
  ('f4200000-0000-4000-8000-000000000032', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000011', 1);
select lives_ok(
  $$insert into public.edit_revisions (id, workspace_id, job_id, lang, rev_no, derived_from)
    values ('f4200000-0000-4000-8000-000000000033', 'f4200000-0000-4000-8000-000000000001',
            'f4200000-0000-4000-8000-000000000012', 'ja', 1, 'f4200000-0000-4000-8000-000000000031')$$,
  'ja 리비전 rev_no 1(ko rev 1과 공존) 허용');
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, lang, rev_no, derived_from)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'ja', 1,
            'f4200000-0000-4000-8000-000000000031')$$,
  '23505', null, '같은 (job, ja, rev_no) 중복 거부');
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, lang, rev_no)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'ja', 2)$$,
  '23514', null, 'ja인데 derived_from 없음 거부');
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, rev_no, derived_from)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 2,
            'f4200000-0000-4000-8000-000000000031')$$,
  '23514', null, 'ko인데 derived_from 있음 거부');
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, lang, rev_no, derived_from)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'ja', 2,
            'f4200000-0000-4000-8000-000000000032')$$,
  '23503', null, 'derived_from이 다른 작업 리비전이면 거부');
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, lang, rev_no)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'en', 1)$$,
  '23514', null, '리비전 lang 허용 외(en) 거부');
select throws_ok(
  $$insert into public.edit_revisions (workspace_id, job_id, lang, rev_no, derived_from)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'ja', 2,
            'f4200000-0000-4000-8000-000000000033')$$,
  '23514', 'edit_revisions.derived_from must reference a ko revision', 'derived_from이 ja 리비전이면 거부');
insert into public.edit_revisions (id, workspace_id, job_id, lang, rev_no, derived_from) values
  ('f4200000-0000-4000-8000-000000000034', 'f4200000-0000-4000-8000-000000000001',
   'f4200000-0000-4000-8000-000000000011', 'ja', 1, 'f4200000-0000-4000-8000-000000000032');

-- 7. 언어별 현재 리비전
select lives_ok(
  $$update public.production_jobs set current_revision_id = 'f4200000-0000-4000-8000-000000000031',
      current_ja_revision_id = 'f4200000-0000-4000-8000-000000000033'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  'current_revision_id(ko)·current_ja_revision_id(ja) 지정');
select throws_ok(
  $$update public.production_jobs set current_ja_revision_id = 'f4200000-0000-4000-8000-000000000034'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23503', null, 'current_ja_revision_id에 다른 작업 ja 리비전 거부');
select throws_ok(
  $$update public.production_jobs set current_ja_revision_id = 'f4200000-0000-4000-8000-000000000031'
    where id = 'f4200000-0000-4000-8000-000000000012'$$,
  '23514', 'production_jobs.current_ja_revision_id must reference a ja revision',
  'current_ja_revision_id에 ko 리비전 거부');

-- 8. render_runs (revision, job, lang) FK
select lives_ok(
  $$insert into public.render_runs (id, workspace_id, job_id, revision_id, lang, idempotency_key, preset_version, status)
    values ('f4200000-0000-4000-8000-000000000051', 'f4200000-0000-4000-8000-000000000001',
            'f4200000-0000-4000-8000-000000000012', 'f4200000-0000-4000-8000-000000000033', 'ja', 'sr-1', 'shopping-v1', 'failed')$$,
  'ja run이 ja 리비전 참조 허용');
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, lang, idempotency_key, preset_version, status)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012',
            'f4200000-0000-4000-8000-000000000033', 'ko', 'sr-2', 'shopping-v1', 'failed')$$,
  '23503', null, 'ko run이 ja 리비전 참조 거부(run 언어 = 리비전 언어)');
select throws_ok(
  $$insert into public.render_runs (workspace_id, job_id, revision_id, lang, idempotency_key, preset_version, status)
    values ('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012',
            'f4200000-0000-4000-8000-000000000033', 'en', 'sr-3', 'shopping-v1', 'failed')$$,
  '23514', null, 'run lang 허용 외(en) 거부');

-- 9. 자산 kind bgm·image, rights
select lives_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000041', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'bgm',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000041.mp3',
            'audio/mpeg', '{"basis":"licensed","author":"a","has_person":false,"source_url":"https://bgm.example.com/t/1"}')$$,
  'bgm 자산(rights.basis licensed·source_url https) 허용');
select lives_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000042', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'image',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000042.png',
            'image/png', '{"note":"basis 미입력"}')$$,
  'image 자산(rights basis 미입력) 허용 — 필수 여부는 승인 때 API');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000043', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'source_upload',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000043.mp4',
            'video/mp4', '{"basis":"downloaded"}')$$,
  '23514', null, 'rights.basis 허용 외 값 거부');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000044', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'source_upload',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000044.mp4',
            'video/mp4', '["own"]')$$,
  '23514', null, 'rights 객체 아님 거부');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000046', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'image',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000046.png', 'image/png', '{"basis":"own","source_url":"javascript:alert(1)"}')$$,
  '23514', null, 'rights.source_url http/https 아님 거부');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000047', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'image',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000047.png', 'image/png', '{"basis":"own","source_url":"https://x.com/a b"}')$$,
  '23514', null, 'rights.source_url 공백 포함 거부');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime, rights)
    values ('f4200000-0000-4000-8000-000000000048', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'image',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000048.png', 'image/png', jsonb_build_object('basis', 'own', 'note',
              (select string_agg(md5(i::text), '') from generate_series(1, 300) i)))$$,
  '23514', null, 'rights 8192바이트 초과 거부');
select throws_ok(
  $$insert into public.production_assets (id, workspace_id, job_id, kind, storage_path, mime)
    values ('f4200000-0000-4000-8000-000000000045', 'f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-000000000012', 'font',
            'f4200000-0000-4000-8000-000000000001/f4200000-0000-4000-8000-000000000012/f4200000-0000-4000-8000-000000000045.ttf', 'font/ttf')$$,
  '23514', null, '자산 kind 허용 외 값 거부');

-- 10. Storage 버킷·정책(task-020 리뷰 후속)
select ok(
  (select allowed_mime_types @> array['image/png', 'image/webp', 'image/jpeg', 'video/mp4', 'audio/mpeg', 'application/json']
     from storage.buckets where id = 'production'),
  'production 버킷 mime: image/png·webp 추가, 기존 유지');
select is(
  (select cardinality(allowed_mime_types) - (select count(distinct m)::int from unnest(allowed_mime_types) m)
     from storage.buckets where id = 'production'),
  0, 'production 버킷 mime 중복 없음');
select is((select relrowsecurity from pg_class where oid = 'storage.objects'::regclass), true, 'storage.objects RLS 활성');
select is(
  (select count(*)::int from pg_policies where schemaname = 'storage' and tablename = 'objects'
     and roles && array['authenticated', 'anon', 'public']::name[]),
  0, 'storage.objects authenticated·anon·public 정책 0건(서명 URL만)');

-- 11. claim: job_kind = 칼럼 값
update public.production_jobs set status = 'preparing' where id = 'f4200000-0000-4000-8000-000000000012';
select is(
  public.claim_production_task('f4200000-0000-4000-8000-000000000001', 'f4200000-0000-4000-8000-0000000000c1')
    ->> 'job_kind',
  'shopping', 'claim: 쇼핑 작업 prepare의 job_kind = shopping');

-- 12. 권한: 새 함수는 브라우저 역할 실행 불가, 새 칼럼은 구성원만 조회(기존 RLS)
select ok(
  not has_function_privilege('authenticated', 'public.production_affiliates_valid(jsonb)', 'execute')
  and not has_function_privilege('anon', 'public.production_jobs_kind_immutable()', 'execute'),
  '새 함수 authenticated·anon 실행 권한 없음');
insert into auth.users (id, email, aud, role) values
  ('f4200000-0000-4000-8000-0000000000e1', 'shop-member@test.local', 'authenticated', 'authenticated');
insert into public.workspace_members (workspace_id, user_id, role) values
  ('f4200000-0000-4000-8000-000000000002', 'f4200000-0000-4000-8000-0000000000e1', 'member');
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"f4200000-0000-4000-8000-0000000000e1","role":"authenticated"}', true);
select is((select count(*)::int from public.production_jobs where affiliates <> '[]'), 0,
  '다른 워크스페이스 구성원: 쇼핑 작업 affiliates 조회 0행');
reset role;

-- 13. ja 리비전이 있는 작업 삭제 연쇄
select lives_ok(
  $$delete from public.production_jobs where id = 'f4200000-0000-4000-8000-000000000012'$$,
  'ja 리비전·ja run·자산이 있는 쇼핑 작업 삭제 성공');
select is(
  (select count(*)::int from public.edit_revisions where job_id = 'f4200000-0000-4000-8000-000000000012')
  + (select count(*)::int from public.render_runs where job_id = 'f4200000-0000-4000-8000-000000000012')
  + (select count(*)::int from public.production_assets where job_id = 'f4200000-0000-4000-8000-000000000012'),
  0, '삭제 연쇄: 리비전(ko·ja)·run·자산 0건');

select * from finish();
rollback;
