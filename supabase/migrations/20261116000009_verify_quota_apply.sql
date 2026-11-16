-- task-006: YouTube 할당량 일 사용량(서버 전체 1개 카운터)과 기록 검증 묶음 반영 RPC. API(service_role)만 사용한다.
-- 근거: tasks/task-006.md#구현 결정, docs/adr/0002-observation-quota.md
-- 오류 SQLSTATE: NR003 = 다른 워크스페이스(또는 없는) 작업·후보·프로필·관측 참조, NR004 = 진행 중이 아닌 작업, 22023 = 잘못된 인자.

-- 1. 할당량 일 사용량 ---------------------------------------------------------
-- day는 America/Los_Angeles 기준 일자(YouTube 할당량 리셋 기준). 키가 하나라 워크스페이스 구분 없음.
create table public.api_quota_daily (
  day date primary key,
  units integer not null default 0 check (units >= 0)
);
comment on table public.api_quota_daily is 'YouTube Data API 일 사용량(unit, 미국 태평양 시간 일자, API 전용)';
alter table public.api_quota_daily enable row level security;
-- 정책 없음: 브라우저 역할은 접근 불가. service_role만 조회·예약.
revoke all on public.api_quota_daily from public, anon, authenticated, service_role;
grant select, insert, update on public.api_quota_daily to service_role;

-- 할당량 일자: 주어진 시각의 America/Los_Angeles 기준 날짜(YouTube 리셋 기준).
create function public.quota_day(p_ts timestamptz)
returns date
language sql
stable
set search_path = ''
as $$
  select (p_ts at time zone 'America/Los_Angeles')::date;
$$;
comment on function public.quota_day(timestamptz) is 'YouTube 할당량 일자(미국 태평양 시간). API 전용';

revoke execute on function public.quota_day(timestamptz) from public, anon, authenticated;
grant execute on function public.quota_day(timestamptz) to service_role;

-- 호출 전에 예약한다. units + p_units <= least(p_limit, 10000)일 때만 원자적으로 더하고 true, 아니면 false(변경 없음).
-- 절대 상한 10,000: 호출자가 더 큰 p_limit을 넘겨도 10,000으로 자른다.
create function public.reserve_quota(p_units integer, p_limit integer)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_day date := public.quota_day(now());
  v_limit integer;
  v_ok boolean;
begin
  if p_units is null or p_units <= 0 or p_limit is null or p_limit < 0 then
    raise exception '잘못된 할당량 인자' using errcode = '22023';
  end if;
  v_limit := least(p_limit, 10000);

  insert into public.api_quota_daily as q (day, units)
    select v_day, p_units
    where p_units <= v_limit
  on conflict (day) do update
    set units = q.units + excluded.units
    where q.units + excluded.units <= v_limit
  returning true into v_ok;

  return coalesce(v_ok, false);
end;
$$;
comment on function public.reserve_quota(integer, integer) is
  'YouTube 할당량 원자적 예약(상한 초과면 false, 변경 없음). API 전용';

revoke execute on function public.reserve_quota(integer, integer) from public, anon, authenticated;
grant execute on function public.reserve_quota(integer, integer) to service_role;

-- 2. 기록 검증 묶음 반영(한 트랜잭션) -----------------------------------------
-- p_payload = {"items": [{candidate_id, observed_at, view_count, license_cc, channel_id, channel_title,
--   is_broadcaster, rep_status, rep_profile_id, verdicts: [{profile_id, status, reason, growth_pct,
--   prev_observation_id}]}]}
-- 관측 id는 여기서 만든다(입력으로 받지 않음). 판정의 curr_observation_id = 새 관측.
-- 하나라도 실패하면 묶음 전체가 롤백된다(이전 판정 유지). 반환: 반영한 후보 수.
create function public.apply_verify_batch(p_workspace uuid, p_job uuid, p_payload jsonb)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_item jsonb;
  v_verdict jsonb;
  v_cand uuid;
  v_obs uuid;
  v_prev uuid;
  v_profile uuid;
  v_n integer := 0;
begin
  perform 1 from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'verify';
  if not found then
    raise exception '이 워크스페이스의 검증 작업이 아닙니다' using errcode = 'NR003';
  end if;
  -- 종료(done·failed)된 작업에는 반영하지 않는다(정리된 시간 초과 작업의 늦은 묶음 방지).
  perform 1 from public.jobs j where j.id = p_job and j.status = 'running' for update;
  if not found then
    raise exception '진행 중인 검증 작업이 아닙니다' using errcode = 'NR004';
  end if;

  for v_item in select e from jsonb_array_elements(coalesce(p_payload -> 'items', '[]')) as t(e) loop
    v_cand := (v_item ->> 'candidate_id')::uuid;
    perform 1 from public.candidates c
      where c.id = v_cand and c.workspace_id = p_workspace
      for update;
    if not found then
      raise exception '이 워크스페이스의 후보가 아닙니다' using errcode = 'NR003';
    end if;

    insert into public.observations
      (workspace_id, candidate_id, observed_at, view_count, license_cc, channel_id, source, job_id)
    values (
      p_workspace,
      v_cand,
      (v_item ->> 'observed_at')::timestamptz,
      (v_item ->> 'view_count')::bigint,
      (v_item ->> 'license_cc')::boolean,
      v_item ->> 'channel_id',
      'youtube_api',
      p_job
    )
    returning id into v_obs;

    for v_verdict in select e from jsonb_array_elements(coalesce(v_item -> 'verdicts', '[]')) as t(e) loop
      v_profile := (v_verdict ->> 'profile_id')::uuid;
      perform 1 from public.profiles p where p.id = v_profile and p.workspace_id = p_workspace;
      if not found then
        raise exception '이 워크스페이스의 프로필이 아닙니다' using errcode = 'NR003';
      end if;
      v_prev := (v_verdict ->> 'prev_observation_id')::uuid;
      if v_prev is not null then
        perform 1 from public.observations o
          where o.id = v_prev and o.candidate_id = v_cand and o.workspace_id = p_workspace;
        if not found then
          raise exception '이 후보의 관측이 아닙니다' using errcode = 'NR003';
        end if;
      end if;

      insert into public.candidate_verdicts as cv
        (workspace_id, candidate_id, profile_id, status, reason, growth_pct,
         prev_observation_id, curr_observation_id, judged_at)
      values (
        p_workspace,
        v_cand,
        v_profile,
        v_verdict ->> 'status',
        v_verdict ->> 'reason',
        (v_verdict ->> 'growth_pct')::numeric,
        v_prev,
        v_obs,
        now()
      )
      on conflict (candidate_id, profile_id) do update
        set status = excluded.status,
            reason = excluded.reason,
            growth_pct = excluded.growth_pct,
            prev_observation_id = excluded.prev_observation_id,
            curr_observation_id = excluded.curr_observation_id,
            judged_at = excluded.judged_at;
    end loop;

    v_profile := (v_item ->> 'rep_profile_id')::uuid;
    perform 1 from public.profiles p where p.id = v_profile and p.workspace_id = p_workspace;
    if not found then
      raise exception '이 워크스페이스의 프로필이 아닙니다' using errcode = 'NR003';
    end if;

    update public.candidates c
      set rep_status = v_item ->> 'rep_status',
          rep_profile_id = v_profile,
          status_changed_at = case
            when c.rep_status is distinct from (v_item ->> 'rep_status') then now()
            else c.status_changed_at
          end,
          license_cc = (v_item ->> 'license_cc')::boolean,
          channel_id = v_item ->> 'channel_id',
          channel_title = v_item ->> 'channel_title',
          is_broadcaster = (v_item ->> 'is_broadcaster')::boolean
      where c.id = v_cand and c.workspace_id = p_workspace;

    v_n := v_n + 1;
  end loop;

  return v_n;
end;
$$;
comment on function public.apply_verify_batch(uuid, uuid, jsonb) is
  '기록 검증 묶음 반영: 관측 추가·프로필별 판정 upsert·대표 판정 갱신을 한 트랜잭션으로. API 전용';

revoke execute on function public.apply_verify_batch(uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function public.apply_verify_batch(uuid, uuid, jsonb) to service_role;
