-- task-007 보안 리뷰 반영: job당 YouTube 조회 상한과 워커 유래 값의 DB 방어선.
-- 근거: tasks/task-007.md#리뷰 반영 결정(security 리뷰)
-- 오류 SQLSTATE: NR003 = 다른 워크스페이스(또는 없는) 수집 작업, NR004 = 진행 중이 아니거나 이 워커가
-- 수령하지 않았거나 중지 요청된 작업, NR005 = 수집 상한 도달, 22023 = 잘못된 인자.

-- 1. job당 YouTube 조회 누적 수 -------------------------------------------------
alter table public.jobs add column lookup_count integer not null default 0 check (lookup_count >= 0);
comment on column public.jobs.lookup_count is '수집 job에서 YouTube 조회를 예약한 후보 수(상한 params.limit, 기본 200)';

-- W-03이 할당량 예약 전에 호출한다. lookup_count + p_n <= 상한일 때만 더하고 새 누적 값을 돌려준다.
create function public.reserve_collect_lookup(p_workspace uuid, p_job uuid, p_worker uuid, p_n integer)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_params jsonb;
  v_count integer;
  v_limit integer;
begin
  if p_workspace is null or p_job is null or p_worker is null or p_n is null or p_n <= 0 then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;
  perform 1 from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect';
  if not found then
    raise exception '이 워크스페이스의 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;
  select j.params, j.lookup_count into v_params, v_count from public.jobs j
    where j.id = p_job and j.status = 'running' and j.claimed_by = p_worker
      and not j.stop_requested
    for update;
  if not found then
    raise exception '이 워커가 진행 중인 작업이 아닙니다' using errcode = 'NR004';
  end if;
  -- params.limit이 1~200 정수면 그 값, 아니면 200(apply_collect_batch·API claim 응답과 같은 규칙)
  v_limit := case
    when jsonb_typeof(v_params -> 'limit') = 'number'
      and (v_params ->> 'limit')::numeric between 1 and 200
      and (v_params ->> 'limit')::numeric % 1 = 0
    then (v_params ->> 'limit')::integer
    else 200
  end;
  if v_count + p_n > v_limit then
    raise exception '수집 상한 도달' using errcode = 'NR005';
  end if;
  update public.jobs j set lookup_count = j.lookup_count + p_n where j.id = p_job
    returning j.lookup_count into v_count;
  return v_count;
end;
$$;
comment on function public.reserve_collect_lookup(uuid, uuid, uuid, integer) is
  '수집 job의 YouTube 조회 수를 상한 안에서 원자적으로 예약. API 전용';

revoke execute on function public.reserve_collect_lookup(uuid, uuid, uuid, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_collect_lookup(uuid, uuid, uuid, integer) to service_role;

-- 2. 워커 유래 값 방어선(API 검증과 같은 목록) ------------------------------------
alter table public.jobs add constraint jobs_error_code_check check (error is null or error in (
  -- 기록 검증(task-006)
  'timeout', 'quota_exceeded', 'upstream_error', 'db_error', 'internal',
  -- 수집(task-007): 오프라인 지연 평가·W-04
  'worker_offline', 'chrome_failed', 'vidiq_changed', 'network', 'stopped_by_user', 'unknown'
));
alter table public.job_profile_runs add constraint job_profile_runs_detail_check check (
  detail is null or detail in ('window_small', 'login_required', 'profile_locked', 'network', 'unknown')
);
-- candidates.format은 000003에서 이미 short·long(null 허용) 제약이 있다.
alter table public.candidates add constraint candidates_market_check check (market in ('KR', 'JP'));
