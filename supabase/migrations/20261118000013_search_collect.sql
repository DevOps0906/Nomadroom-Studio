-- task-019: YouTube 검색 후보 수집(서버 동기 처리). API(service_role)만 사용한다.
-- 근거: tasks/task-019.md#착수 결정, docs/adr/0002-observation-quota.md(2026-11-17 결정)
-- 검색 job = kind 'collect' + params.source = 'youtube_search'. 워커가 수령하지 않는다(claimed_by 없음,
-- queued·retrying 없음). 워커용 RPC(apply_collect_batch·reserve_collect_lookup)는 바꾸지 않는다.
-- 오류 SQLSTATE: NR003 = 다른 워크스페이스(또는 없는) 작업·프로필, 작업에 속하지 않은 프로필
--               NR004 = 진행 중이 아니거나 중지 요청된 검색 작업
--               NR005 = 작업 수집 상한(params.limit, 기본·최대 200) 초과
--               NR008 = 검색 수집 작업은 이 RPC 대상이 아님(retry·stop), 22023 = 잘못된 인자.
-- jobs.error의 `upstream_error`·`quota_exceeded`는 000011 제약에 이미 있다.

-- 1. 검색 전용 일 사용량 --------------------------------------------------------
alter table public.api_quota_daily
  add column search_units integer not null default 0 check (search_units >= 0);
comment on column public.api_quota_daily.search_units is
  'YouTube 검색 사용량(unit). units(전체)에도 함께 더한다';

-- 검색 호출 전에 예약한다. 검색 일 상한(p_search_limit)과 전체 방어선(p_limit)을 한 문장으로 함께 확인하고
-- 둘 다 통과할 때만 units·search_units에 원자적으로 더한 뒤 true, 아니면 false(변경 없음).
-- 절대 상한 10,000: 호출자가 더 큰 값을 넘겨도 10,000으로 자른다.
create function public.reserve_search_quota(p_units integer, p_search_limit integer, p_limit integer)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_day date := public.quota_day(now());
  v_limit integer;
  v_search_limit integer;
  v_ok boolean;
begin
  if p_units is null or p_units <= 0 or p_limit is null or p_limit < 0
     or p_search_limit is null or p_search_limit < 0 then
    raise exception '잘못된 할당량 인자' using errcode = '22023';
  end if;
  v_limit := least(p_limit, 10000);
  v_search_limit := least(p_search_limit, v_limit);

  insert into public.api_quota_daily as q (day, units, search_units)
    select v_day, p_units, p_units
    where p_units <= v_search_limit
  on conflict (day) do update
    set units = q.units + excluded.units,
        search_units = q.search_units + excluded.search_units
    where q.units + excluded.units <= v_limit
      and q.search_units + excluded.search_units <= v_search_limit
  returning true into v_ok;

  return coalesce(v_ok, false);
end;
$$;
comment on function public.reserve_search_quota(integer, integer, integer) is
  'YouTube 검색 할당량 원자적 예약(검색 상한·전체 방어선 중 하나라도 초과면 false, 변경 없음). API 전용';

revoke execute on function public.reserve_search_quota(integer, integer, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_search_quota(integer, integer, integer) to service_role;

-- 2. 검색 job은 워커가 수령할 수 없다(DB 방어선) ----------------------------------
alter table public.jobs add constraint jobs_search_not_claimable_check check (
  params ->> 'source' is distinct from 'youtube_search'
  or (claimed_by is null and status not in ('queued', 'retrying'))
);

-- 3. 검색 결과 반영(프로필 1개분, 한 트랜잭션) -------------------------------------
-- p_payload = {"items": [{video_id, title, thumbnail_url, category, format, market, channel_id,
--   channel_title, license_cc, is_broadcaster, observed_at, view_count, rep_status, rep_profile_id,
--   verdicts: [{profile_id, status, reason}]}]}
-- 이미 있는 video_id(동시 요청 포함)는 건너뛴다. 새 후보마다 1차 관측 1건과 이번 실행 프로필별 판정을 넣는다.
-- 끝나면 p_profile의 실행 행을 done(collected_count += 새 후보 수)으로 둔다. 하나라도 실패하면 전체 롤백.
-- 반환: 새로 넣은 후보 수.
create function public.apply_search_batch(
  p_workspace uuid, p_job uuid, p_profile uuid, p_payload jsonb
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_profile_ids uuid[];
  v_params jsonb;
  v_limit integer;
  v_total integer;
  v_position integer;
  v_item jsonb;
  v_verdict jsonb;
  v_vprofile uuid;
  v_rep uuid;
  v_cand uuid;
  v_obs uuid;
  v_n integer := 0;
begin
  if p_workspace is null or p_job is null or p_profile is null then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;

  perform 1 from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect'
      and j.params ->> 'source' = 'youtube_search';
  if not found then
    raise exception '이 워크스페이스의 검색 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;
  select j.profile_ids, j.params into v_profile_ids, v_params from public.jobs j
    where j.id = p_job and j.status = 'running' and not j.stop_requested
    for update;
  if not found then
    raise exception '진행 중인 검색 수집 작업이 아닙니다' using errcode = 'NR004';
  end if;

  v_position := array_position(v_profile_ids, p_profile);
  if v_position is null then
    raise exception '작업에 속한 프로필이 아닙니다' using errcode = 'NR003';
  end if;
  -- 작업 프로필이 모두 이 워크스페이스 것인지(판정·대표 프로필은 이 목록 안에서만 허용)
  perform 1 from unnest(v_profile_ids) as t(pid)
    where not exists (
      select 1 from public.profiles p where p.id = t.pid and p.workspace_id = p_workspace
    );
  if found then
    raise exception '이 워크스페이스의 프로필이 아닙니다' using errcode = 'NR003';
  end if;

  -- 수집 상한: params.limit이 1~200 정수면 그 값, 아니면 200(apply_collect_batch와 같은 규칙)
  v_limit := case
    when jsonb_typeof(v_params -> 'limit') = 'number' then
      case
        when (v_params ->> 'limit')::numeric between 1 and 200
          and (v_params ->> 'limit')::numeric % 1 = 0
        then (v_params ->> 'limit')::integer
        else 200
      end
    else 200
  end;
  select coalesce(sum(r.collected_count), 0)::integer into v_total
    from public.job_profile_runs r where r.job_id = p_job;

  for v_item in select e from jsonb_array_elements(coalesce(p_payload -> 'items', '[]')) as t(e) loop
    v_rep := (v_item ->> 'rep_profile_id')::uuid;
    if v_rep is null or array_position(v_profile_ids, v_rep) is null then
      raise exception '작업에 속한 프로필이 아닙니다' using errcode = 'NR003';
    end if;

    v_cand := null;
    insert into public.candidates
      (workspace_id, video_id, title, thumbnail_url, genre, category, format, market,
       channel_id, channel_title, license_cc, is_broadcaster, rep_status, rep_profile_id,
       status_changed_at, first_job_id)
    values (
      p_workspace,
      v_item ->> 'video_id',
      v_item ->> 'title',
      v_item ->> 'thumbnail_url',
      null,
      v_item ->> 'category',
      v_item ->> 'format',
      v_item ->> 'market',
      v_item ->> 'channel_id',
      v_item ->> 'channel_title',
      (v_item ->> 'license_cc')::boolean,
      coalesce((v_item ->> 'is_broadcaster')::boolean, false),
      v_item ->> 'rep_status',
      v_rep,
      now(),
      p_job
    )
    on conflict (workspace_id, video_id) do nothing
    returning id into v_cand;

    if v_cand is null then
      continue;  -- 이미 있는 후보
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
      v_vprofile := (v_verdict ->> 'profile_id')::uuid;
      if v_vprofile is null or array_position(v_profile_ids, v_vprofile) is null then
        raise exception '작업에 속한 프로필이 아닙니다' using errcode = 'NR003';
      end if;
      insert into public.candidate_verdicts
        (workspace_id, candidate_id, profile_id, status, reason, growth_pct,
         prev_observation_id, curr_observation_id, judged_at)
      values (p_workspace, v_cand, v_vprofile, v_verdict ->> 'status', v_verdict ->> 'reason',
              null, null, v_obs, now());
    end loop;

    v_n := v_n + 1;
  end loop;

  if v_total + v_n > v_limit then
    raise exception '작업 수집 상한 초과' using errcode = 'NR005';
  end if;

  insert into public.job_profile_runs as r
    (workspace_id, job_id, profile_id, position, collected_count, status, updated_at)
  values (p_workspace, p_job, p_profile, v_position - 1, v_n, 'done', now())
  on conflict (job_id, profile_id) do update
    set collected_count = r.collected_count + excluded.collected_count,
        status = 'done',
        updated_at = now();

  return v_n;
end;
$$;
comment on function public.apply_search_batch(uuid, uuid, uuid, jsonb) is
  '검색 수집 반영(프로필 1개분): 새 후보·1차 관측·프로필별 판정·대표 판정·실행 행 done을 한 트랜잭션으로. API 전용';

revoke execute on function public.apply_search_batch(uuid, uuid, uuid, jsonb)
  from public, anon, authenticated;
grant execute on function public.apply_search_batch(uuid, uuid, uuid, jsonb) to service_role;

-- 4. retry·stop RPC는 검색 job을 거부한다(검색 재시도는 API가 직접, 중지는 지원 안 함) -----
-- 본문은 000012와 같고 검색 job 확인(NR008)만 더했다.
create or replace function public.retry_collect_job(p_workspace uuid, p_job uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_job public.jobs%rowtype;
  v_limit integer;
  v_collected integer;
  v_resume uuid;
  v_resume_pos integer;
begin
  if p_workspace is null or p_job is null then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;

  select * into v_job from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect'
    for update;
  if not found then
    raise exception '이 워크스페이스의 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;
  if v_job.params ->> 'source' = 'youtube_search' then
    raise exception '검색 수집 작업은 이 RPC로 재시도하지 않습니다' using errcode = 'NR008';
  end if;
  if v_job.status <> 'failed' or v_job.retry_count >= 3 or v_job.stop_requested then
    raise exception '재시도 불가' using errcode = 'NR006';
  end if;

  v_limit := case
    when jsonb_typeof(v_job.params -> 'limit') = 'number' then
      case
        when (v_job.params ->> 'limit')::numeric between 1 and 200
          and (v_job.params ->> 'limit')::numeric % 1 = 0
        then (v_job.params ->> 'limit')::integer
        else 200
      end
    else 200
  end;
  select coalesce(sum(r.collected_count), 0)::integer into v_collected
    from public.job_profile_runs r where r.job_id = p_job;
  if v_job.lookup_count >= v_limit or v_collected >= v_limit then
    raise exception '이 작업의 조회 상한 도달' using errcode = 'NR005';
  end if;

  perform 1 from public.jobs j
    where j.workspace_id = p_workspace and j.kind = 'collect' and j.id <> p_job
      and j.status in ('queued', 'running', 'retrying');
  if found then
    raise exception '다른 수집 작업이 진행 중입니다' using errcode = 'NR007';
  end if;

  select t.pid, (t.ord - 1)::integer into v_resume, v_resume_pos
    from unnest(v_job.profile_ids) with ordinality as t(pid, ord)
    where not exists (
      select 1 from public.job_profile_runs r
        where r.job_id = p_job and r.profile_id = t.pid and r.status = 'done'
    )
    order by t.ord
    limit 1;
  if v_resume is null then
    raise exception '재시도할 프로필이 없습니다' using errcode = 'NR006';
  end if;

  update public.job_profile_runs r
    set status = 'pending', updated_at = now()
    where r.job_id = p_job and r.status = 'failed' and r.position >= v_resume_pos;

  update public.jobs j
    set status = 'retrying',
        retry_count = j.retry_count + 1,
        error = null,
        finished_at = null,
        claimed_by = null,
        params = j.params || jsonb_build_object('resume_from_profile_id', v_resume)
    where j.id = p_job
    returning * into v_job;

  return jsonb_build_object(
    'id', v_job.id, 'status', v_job.status, 'stop_requested', v_job.stop_requested,
    'retry_count', v_job.retry_count
  );
end;
$$;

create or replace function public.stop_collect_job(p_workspace uuid, p_job uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_job public.jobs%rowtype;
begin
  if p_workspace is null or p_job is null then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;

  select * into v_job from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect'
    for update;
  if not found then
    raise exception '이 워크스페이스의 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;
  if v_job.params ->> 'source' = 'youtube_search' then
    raise exception '검색 수집 작업은 중지할 수 없습니다' using errcode = 'NR008';
  end if;

  if v_job.status in ('queued', 'retrying') then
    update public.jobs j
      set status = 'stopped', error = 'stopped_by_user', finished_at = now()
      where j.id = p_job
      returning * into v_job;
  elsif v_job.status = 'running' then
    update public.jobs j set stop_requested = true where j.id = p_job
      returning * into v_job;
  else
    raise exception '이미 종료된 작업입니다' using errcode = 'NR006';
  end if;

  return jsonb_build_object(
    'id', v_job.id, 'status', v_job.status, 'stop_requested', v_job.stop_requested,
    'retry_count', v_job.retry_count
  );
end;
$$;

revoke execute on function public.retry_collect_job(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.stop_collect_job(uuid, uuid) from public, anon, authenticated;
grant execute on function public.retry_collect_job(uuid, uuid) to service_role;
grant execute on function public.stop_collect_job(uuid, uuid) to service_role;
