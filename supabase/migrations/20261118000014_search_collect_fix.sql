-- task-019 리뷰 반영: apply_search_batch 소속 검사 범위 축소, 검색 할당량 환불 RPC.
-- 근거: tasks/task-019.md#착수 결정(리뷰 반영). 000013은 적용되었으므로 수정하지 않는다.
-- 오류 SQLSTATE는 000013과 같다(NR003·NR004·NR005·22023).

-- 1. apply_search_batch: 실제로 쓰는 프로필(p_profile·판정·대표)만 워크스페이스 소속을 확인한다 ----
create or replace function public.apply_search_batch(
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
  -- 소속 검사는 실제로 쓰는 프로필(p_profile·판정·대표)만 한다.
  -- job.profile_ids에 삭제된 프로필이 남아 있어도 쓰지 않으면 실패하지 않는다.
  perform 1 from public.profiles p where p.id = p_profile and p.workspace_id = p_workspace;
  if not found then
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
    perform 1 from public.profiles p where p.id = v_rep and p.workspace_id = p_workspace;
    if not found then
      raise exception '이 워크스페이스의 프로필이 아닙니다' using errcode = 'NR003';
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
      perform 1 from public.profiles p where p.id = v_vprofile and p.workspace_id = p_workspace;
      if not found then
        raise exception '이 워크스페이스의 프로필이 아닙니다' using errcode = 'NR003';
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

-- 2. 검색 할당량 환불 --------------------------------------------------------------
-- reserve_search_quota 뒤 job 생성·재시도 전이가 실패했을 때 API가 호출한다(검색을 하지 않았음).
-- 오늘(quota_day) 행의 units·search_units에서 빼되 0 아래로 내려가지 않는다. 행이 없으면 아무것도 안 함.
create function public.release_search_quota(p_units integer)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if p_units is null or p_units <= 0 then
    raise exception '잘못된 할당량 인자' using errcode = '22023';
  end if;
  update public.api_quota_daily q
    set units = greatest(q.units - p_units, 0),
        search_units = greatest(q.search_units - p_units, 0)
    where q.day = public.quota_day(now());
end;
$$;
comment on function public.release_search_quota(integer) is
  '검색 할당량 예약 되돌리기(0 아래로 내려가지 않음). API 전용';

revoke execute on function public.release_search_quota(integer) from public, anon, authenticated;
grant execute on function public.release_search_quota(integer) to service_role;
