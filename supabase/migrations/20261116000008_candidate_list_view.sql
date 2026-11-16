-- task-011: 후보 목록·근거 조회용 뷰(A-02·A-04·A-06). API(service_role)만 조회한다.
-- 대표 판정 = candidate_verdicts.profile_id = candidates.rep_profile_id. 그 판정의 prev·curr 관측을 붙인다.
-- display_status: used=true → 'used', 아니면 coalesce(rep_status, 'pending')(판정 전 후보는 근거 대기).
-- 조인은 workspace_id도 맞춘다(다른 워크스페이스 행이 섞이지 않게).

create view public.candidate_list_v
with (security_invoker = true)
as
select
  c.id,
  c.workspace_id,
  c.video_id,
  c.title,
  c.thumbnail_url,
  c.genre,
  c.category,
  c.format,
  c.market,
  c.channel_id,
  c.channel_title,
  c.license_cc,
  c.is_broadcaster,
  c.used,
  c.used_at,
  c.rep_status,
  c.rep_profile_id,
  c.status_changed_at,
  c.first_job_id,
  c.created_at,
  case when c.used then 'used' else coalesce(c.rep_status, 'pending') end as display_status,
  v.growth_pct,
  v.reason,
  po.observed_at as prev_observed_at,
  po.view_count as prev_view_count,
  co.observed_at as curr_observed_at,
  co.view_count as curr_view_count,
  (
    select max(o.observed_at)
    from public.observations o
    where o.candidate_id = c.id and o.workspace_id = c.workspace_id
  ) as latest_observed_at
from public.candidates c
left join public.candidate_verdicts v
  on v.candidate_id = c.id
 and v.profile_id = c.rep_profile_id
 and v.workspace_id = c.workspace_id
left join public.observations po
  on po.id = v.prev_observation_id and po.workspace_id = c.workspace_id
left join public.observations co
  on co.id = v.curr_observation_id and co.workspace_id = c.workspace_id;

comment on view public.candidate_list_v is '후보 + 대표 판정·관측(표시 상태 used 우선, API service_role 전용)';

-- 브라우저 역할은 조회 불가(기본 권한 회수는 000005), API만 명시 grant
revoke all on public.candidate_list_v from public, anon, authenticated;
grant select on public.candidate_list_v to service_role;
