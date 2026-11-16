-- task-006 reserve_quota · apply_verify_batch RPC 테스트 (supabase test db)
begin;
create extension if not exists pgtap with schema extensions;
select plan(42);

insert into public.workspaces (id, name) values
  ('cccccccc-0000-4000-8000-000000000001', 'verify-ws'),
  ('cccccccc-0000-4000-8000-000000000002', 'verify-other-ws');
insert into public.profiles (id, workspace_id, name, market, max_growth_pct) values
  ('cccccccc-0000-4000-8000-0000000000a1', 'cccccccc-0000-4000-8000-000000000001', 'p1', 'KR', 10),
  ('cccccccc-0000-4000-8000-0000000000b1', 'cccccccc-0000-4000-8000-000000000002', 'o1', 'KR', 10);
insert into public.jobs (id, workspace_id, kind, status, idempotency_key) values
  ('cccccccc-0000-4000-8000-0000000000f1', 'cccccccc-0000-4000-8000-000000000001', 'verify', 'running', 'k1'),
  ('cccccccc-0000-4000-8000-0000000000f2', 'cccccccc-0000-4000-8000-000000000002', 'verify', 'running', 'k2'),
  ('cccccccc-0000-4000-8000-0000000000f3', 'cccccccc-0000-4000-8000-000000000001', 'verify', 'done', 'k3'),
  ('cccccccc-0000-4000-8000-0000000000f4', 'cccccccc-0000-4000-8000-000000000001', 'verify', 'failed', 'k4');
insert into public.candidates (id, workspace_id, video_id, title, market, rep_status, rep_profile_id, status_changed_at) values
  ('cccccccc-0000-4000-8000-0000000000c1', 'cccccccc-0000-4000-8000-000000000001', 'vid-c1', 'c1', 'KR',
   'pending', 'cccccccc-0000-4000-8000-0000000000a1', '2026-01-01T00:00:00Z'),
  ('cccccccc-0000-4000-8000-0000000000c2', 'cccccccc-0000-4000-8000-000000000001', 'vid-c2', 'c2', 'KR',
   null, null, null),
  ('cccccccc-0000-4000-8000-0000000000d1', 'cccccccc-0000-4000-8000-000000000002', 'vid-d1', 'd1', 'KR',
   null, null, null);
insert into public.observations (id, workspace_id, candidate_id, observed_at, view_count) values
  ('cccccccc-0000-4000-8000-0000000000e1', 'cccccccc-0000-4000-8000-000000000001',
   'cccccccc-0000-4000-8000-0000000000c1', '2026-01-01T00:00:00Z', 1000),
  ('cccccccc-0000-4000-8000-0000000000e2', 'cccccccc-0000-4000-8000-000000000002',
   'cccccccc-0000-4000-8000-0000000000d1', '2026-01-01T00:00:00Z', 500);

-- 1. 함수 속성
select is(
  (select prosecdef from pg_proc where oid = 'public.reserve_quota(integer, integer)'::regprocedure),
  false, 'reserve_quota security invoker');
select is(
  (select proconfig from pg_proc where oid = 'public.reserve_quota(integer, integer)'::regprocedure),
  array['search_path=""'], 'reserve_quota search_path 비움');
select is(
  (select prosecdef from pg_proc where oid = 'public.apply_verify_batch(uuid, uuid, jsonb)'::regprocedure),
  false, 'apply_verify_batch security invoker');
select is(
  (select proconfig from pg_proc where oid = 'public.apply_verify_batch(uuid, uuid, jsonb)'::regprocedure),
  array['search_path=""'], 'apply_verify_batch search_path 비움');
select is(
  (select proconfig from pg_proc where oid = 'public.quota_day(timestamptz)'::regprocedure),
  array['search_path=""'], 'quota_day search_path 비움');
select ok(
  (select relrowsecurity from pg_class where oid = 'public.api_quota_daily'::regclass),
  'api_quota_daily RLS 활성');

-- 2. 브라우저 역할 거부
set local role authenticated;
select throws_ok($$select public.reserve_quota(1, 8000)$$, '42501', null, 'authenticated reserve_quota 거부');
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1', '{}')$$,
  '42501', null, 'authenticated apply_verify_batch 거부');
select throws_ok($$select * from public.api_quota_daily$$, '42501', null, 'authenticated api_quota_daily 조회 거부');
reset role;
set local role anon;
select throws_ok($$select public.reserve_quota(1, 8000)$$, '42501', null, 'anon reserve_quota 거부');
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1', '{}')$$,
  '42501', null, 'anon apply_verify_batch 거부');
select throws_ok($$select * from public.api_quota_daily$$, '42501', null, 'anon api_quota_daily 조회 거부');
select throws_ok($$select public.quota_day(now())$$, '42501', null, 'anon quota_day 거부');
reset role;

delete from public.api_quota_daily;
set local role service_role;
-- 3. reserve_quota: 상한 이하만 원자적으로 더한다
select is(public.reserve_quota(5, 10), true, '첫 예약 5/10');
select is(public.reserve_quota(5, 10), true, '상한과 같으면 허용 10/10');
select is(public.reserve_quota(1, 10), false, '상한 초과 거부');
select is((select units from public.api_quota_daily), 10, '거부 시 사용량 그대로');
select is((select day from public.api_quota_daily), public.quota_day(now()), '예약 일자는 quota_day(now())');
reset role;
delete from public.api_quota_daily;
set local role service_role;
select is(public.reserve_quota(11, 10), false, '첫 예약도 상한 초과면 거부');
select is((select count(*)::int from public.api_quota_daily), 0, '거부 시 행 없음');
select throws_ok($$select public.reserve_quota(0, 10)$$, '22023', null, '0 unit 예약 거부');

-- 3-1. 절대 상한 10,000: p_limit이 더 커도 10,000으로 자른다
select is(public.reserve_quota(10001, 20000), false, 'p_limit 20000이어도 10001 예약 거부');
select is(public.reserve_quota(10000, 20000), true, '10000까지는 허용');
select is(public.reserve_quota(1, 20000), false, '10000 도달 후 추가 거부(p_limit 무시)');

-- 3-2. quota_day: UTC와 LA 일자가 갈리는 고정 시각
select is(('2026-03-10T03:00:00Z'::timestamptz at time zone 'UTC')::date, '2026-03-10'::date, '전제: UTC 일자 3/10');
select is(public.quota_day('2026-03-10T03:00:00Z'), '2026-03-09'::date, 'LA 기준 3/9(UTC 03시 = 전날 19시 PST)');
select is(public.quota_day('2026-07-01T07:30:00Z'), '2026-07-01'::date, '여름(PDT, UTC-7) 07:30Z는 LA 7/1 00:30');

-- 4. apply_verify_batch 정상 반영
select is(
  public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1',
    '{"items": [{"candidate_id": "cccccccc-0000-4000-8000-0000000000c1", "observed_at": "2026-01-02T00:00:00Z",
      "view_count": 1005, "license_cc": true, "channel_id": "UCx", "channel_title": "채널 X",
      "is_broadcaster": false, "rep_status": "producible", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000a1",
      "verdicts": [{"profile_id": "cccccccc-0000-4000-8000-0000000000a1", "status": "producible", "reason": null,
        "growth_pct": 0.5, "prev_observation_id": "cccccccc-0000-4000-8000-0000000000e1"}]}]}'),
  1, '1건 반영');
select is(
  (select count(*)::int from public.observations where candidate_id = 'cccccccc-0000-4000-8000-0000000000c1'
     and job_id = 'cccccccc-0000-4000-8000-0000000000f1' and view_count = 1005 and license_cc),
  1, '관측 추가(job_id·license_cc 기록)');
select is(
  (select v.curr_observation_id = o.id and v.status = 'producible' and v.growth_pct = 0.5
     from public.candidate_verdicts v
     join public.observations o on o.candidate_id = v.candidate_id and o.view_count = 1005
     where v.candidate_id = 'cccccccc-0000-4000-8000-0000000000c1'),
  true, '판정 curr = 새 관측');
select is(
  (select rep_status || '|' || license_cc::text || '|' || channel_title || '|' ||
          (status_changed_at > '2026-01-01T00:00:00Z')::text
     from public.candidates where id = 'cccccccc-0000-4000-8000-0000000000c1'),
  'producible|true|채널 X|true', '후보 대표 판정·라이선스·채널·상태 변경 시각 갱신');

-- 같은 상태면 status_changed_at 유지
update public.candidates set status_changed_at = '2026-01-05T00:00:00Z'
  where id = 'cccccccc-0000-4000-8000-0000000000c1';
select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1',
  '{"items": [{"candidate_id": "cccccccc-0000-4000-8000-0000000000c1", "observed_at": "2026-01-03T00:00:00Z",
    "view_count": 1010, "license_cc": true, "channel_id": "UCx", "channel_title": "채널 X",
    "is_broadcaster": false, "rep_status": "producible", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000a1",
    "verdicts": [{"profile_id": "cccccccc-0000-4000-8000-0000000000a1", "status": "producible", "reason": null,
      "growth_pct": 0.5, "prev_observation_id": null}]}]}');
select is(
  (select status_changed_at from public.candidates where id = 'cccccccc-0000-4000-8000-0000000000c1'),
  '2026-01-05T00:00:00Z'::timestamptz, '상태가 같으면 status_changed_at 유지');
select is(
  (select count(*)::int from public.candidate_verdicts where candidate_id = 'cccccccc-0000-4000-8000-0000000000c1'),
  1, '판정은 후보·프로필당 1행(upsert)');

-- 5. 중간 실패 → 묶음 전체 롤백(첫 항목도 남지 않음)
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1',
    '{"items": [
      {"candidate_id": "cccccccc-0000-4000-8000-0000000000c2", "observed_at": "2026-01-03T00:00:00Z",
       "view_count": 7, "license_cc": null, "channel_id": "UCy", "channel_title": "Y", "is_broadcaster": false,
       "rep_status": "pending", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000a1",
       "verdicts": [{"profile_id": "cccccccc-0000-4000-8000-0000000000a1", "status": "pending", "reason": "no_prev",
         "growth_pct": null, "prev_observation_id": null}]},
      {"candidate_id": "cccccccc-0000-4000-8000-0000000000d1", "observed_at": "2026-01-03T00:00:00Z",
       "view_count": 7, "license_cc": null, "channel_id": "UCy", "channel_title": "Y", "is_broadcaster": false,
       "rep_status": "pending", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000a1", "verdicts": []}]}')$$,
  'NR003', null, '다른 워크스페이스 후보가 섞이면 실패');
select is(
  (select count(*)::int from public.observations where candidate_id = 'cccccccc-0000-4000-8000-0000000000c2'),
  0, '롤백: 첫 항목 관측 없음');
select is(
  (select rep_status from public.candidates where id = 'cccccccc-0000-4000-8000-0000000000c2'),
  null, '롤백: 첫 항목 대표 판정 그대로');

-- 6. 다른 워크스페이스 작업·프로필 참조 거부
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f2', '{"items": []}')$$,
  'NR003', null, '다른 워크스페이스 작업 거부');
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1',
    '{"items": [{"candidate_id": "cccccccc-0000-4000-8000-0000000000c2", "observed_at": "2026-01-03T00:00:00Z",
      "view_count": 7, "license_cc": null, "channel_id": "UCy", "channel_title": "Y", "is_broadcaster": false,
      "rep_status": "pending", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000b1",
      "verdicts": [{"profile_id": "cccccccc-0000-4000-8000-0000000000b1", "status": "pending", "reason": "no_prev",
        "growth_pct": null, "prev_observation_id": null}]}]}')$$,
  'NR003', null, '다른 워크스페이스 프로필 거부');
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f1',
    '{"items": [{"candidate_id": "cccccccc-0000-4000-8000-0000000000c2", "observed_at": "2026-01-03T00:00:00Z",
      "view_count": 7, "license_cc": null, "channel_id": "UCy", "channel_title": "Y", "is_broadcaster": false,
      "rep_status": "pending", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000a1",
      "verdicts": [{"profile_id": "cccccccc-0000-4000-8000-0000000000a1", "status": "pending", "reason": "no_prev",
        "growth_pct": null, "prev_observation_id": "cccccccc-0000-4000-8000-0000000000e2"}]}]}')$$,
  'NR003', null, '다른 워크스페이스 관측을 prev로 참조 거부');

-- 7. 종료된 작업에는 반영 거부(묶음 전체 롤백)
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f3',
    '{"items": [{"candidate_id": "cccccccc-0000-4000-8000-0000000000c2", "observed_at": "2026-01-03T00:00:00Z",
      "view_count": 7, "license_cc": null, "channel_id": "UCy", "channel_title": "Y", "is_broadcaster": false,
      "rep_status": "pending", "rep_profile_id": "cccccccc-0000-4000-8000-0000000000a1", "verdicts": []}]}')$$,
  'NR004', null, 'done 작업 반영 거부');
select throws_ok(
  $$select public.apply_verify_batch('cccccccc-0000-4000-8000-000000000001', 'cccccccc-0000-4000-8000-0000000000f4', '{"items": []}')$$,
  'NR004', null, 'failed 작업 반영 거부');
select is(
  (select count(*)::int from public.observations where candidate_id = 'cccccccc-0000-4000-8000-0000000000c2'),
  0, '종료된 작업: 관측 추가 없음');
reset role;

select * from finish();
rollback;
