-- task-007: 수집 후보 묶음 반영 RPC. API(service_role)만 사용한다.
-- 근거: tasks/task-007.md#구현 결정, docs/02_ARCHITECTURE.md#3-1·#3-3
-- 오류 SQLSTATE: NR003 = 다른 워크스페이스(또는 없는) 작업·프로필, 또는 작업에 속하지 않은 프로필
--               NR004 = 진행 중이 아니거나 이 워커가 수령하지 않았거나 중지 요청된 작업
--               NR005 = 작업 수집 상한(params.limit, 기본·최대 200) 초과, 22023 = 잘못된 인자.

-- p_payload = {"items": [{video_id, title, thumbnail_url, genre, category, format, market,
--   channel_id, channel_title, license_cc, is_broadcaster, observed_at, view_count, status, reason}]}
-- 이미 있는 video_id(동시 요청 포함)는 건너뛴다(기존 후보에 판정을 만들지 않음).
-- 새 후보마다 1차 관측 1건·해당 프로필 판정 1건을 넣고 대표 판정 = 그 판정.
-- 하나라도 실패하면 전체 롤백. 반환: 새로 넣은 후보 수(job_profile_runs.collected_count에 더함).
-- 프로필 k의 후보가 들어오면 position < k인 running 행은 done(다음 프로필로 넘어감, 02#3-3).
create function public.apply_collect_batch(
  p_workspace uuid, p_job uuid, p_worker uuid, p_profile uuid, p_payload jsonb
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
  v_cand uuid;
  v_obs uuid;
  v_status text;
  v_n integer := 0;
begin
  if p_workspace is null or p_job is null or p_worker is null or p_profile is null then
    raise exception '잘못된 인자' using errcode = '22023';
  end if;

  perform 1 from public.jobs j
    where j.id = p_job and j.workspace_id = p_workspace and j.kind = 'collect';
  if not found then
    raise exception '이 워크스페이스의 수집 작업이 아닙니다' using errcode = 'NR003';
  end if;
  -- 종료·중지(요청 포함)된 작업, 다른 워커가 수령한 작업에는 반영하지 않는다(행 잠금으로 W-04와 직렬화).
  select j.profile_ids, j.params into v_profile_ids, v_params from public.jobs j
    where j.id = p_job and j.status = 'running' and j.claimed_by = p_worker
      and not j.stop_requested
    for update;
  if not found then
    raise exception '이 워커가 진행 중인 작업이 아닙니다' using errcode = 'NR004';
  end if;

  v_position := array_position(v_profile_ids, p_profile);
  if v_position is null then
    raise exception '작업에 속한 프로필이 아닙니다' using errcode = 'NR003';
  end if;
  perform 1 from public.profiles p where p.id = p_profile and p.workspace_id = p_workspace;
  if not found then
    raise exception '이 워크스페이스의 프로필이 아닙니다' using errcode = 'NR003';
  end if;

  -- 수집 상한: params.limit이 1~200 정수면 그 값, 아니면 200(API claim 응답과 같은 규칙)
  v_limit := case
    when jsonb_typeof(v_params -> 'limit') = 'number'
      and (v_params ->> 'limit')::numeric between 1 and 200
      and (v_params ->> 'limit')::numeric % 1 = 0
    then (v_params ->> 'limit')::integer
    else 200
  end;
  select coalesce(sum(r.collected_count), 0)::integer into v_total
    from public.job_profile_runs r where r.job_id = p_job;

  for v_item in select e from jsonb_array_elements(coalesce(p_payload -> 'items', '[]')) as t(e) loop
    v_status := v_item ->> 'status';
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
      v_item ->> 'genre',
      v_item ->> 'category',
      v_item ->> 'format',
      v_item ->> 'market',
      v_item ->> 'channel_id',
      v_item ->> 'channel_title',
      (v_item ->> 'license_cc')::boolean,
      coalesce((v_item ->> 'is_broadcaster')::boolean, false),
      v_status,
      p_profile,
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

    insert into public.candidate_verdicts
      (workspace_id, candidate_id, profile_id, status, reason, growth_pct,
       prev_observation_id, curr_observation_id, judged_at)
    values (p_workspace, v_cand, p_profile, v_status, v_item ->> 'reason', null, null, v_obs, now());

    v_n := v_n + 1;
  end loop;

  if v_total + v_n > v_limit then
    raise exception '작업 수집 상한 초과' using errcode = 'NR005';
  end if;

  update public.job_profile_runs r
    set status = 'done', updated_at = now()
    where r.job_id = p_job and r.status = 'running' and r.position < v_position - 1;

  insert into public.job_profile_runs as r
    (workspace_id, job_id, profile_id, position, collected_count, status, updated_at)
  values (p_workspace, p_job, p_profile, v_position - 1, v_n, 'running', now())
  on conflict (job_id, profile_id) do update
    set collected_count = r.collected_count + excluded.collected_count,
        status = case when r.status = 'pending' then 'running' else r.status end,
        updated_at = now();

  return v_n;
end;
$$;
comment on function public.apply_collect_batch(uuid, uuid, uuid, uuid, jsonb) is
  '수집 후보 묶음 반영: 새 후보·1차 관측·판정·대표 판정·프로필별 수집 수를 한 트랜잭션으로. API 전용';

revoke execute on function public.apply_collect_batch(uuid, uuid, uuid, uuid, jsonb)
  from public, anon, authenticated;
grant execute on function public.apply_collect_batch(uuid, uuid, uuid, uuid, jsonb) to service_role;
