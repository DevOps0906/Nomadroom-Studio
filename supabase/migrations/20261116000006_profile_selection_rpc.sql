-- task-010: 프로필 선택(최대 3) 원자적 갱신. API(service_role)만 실행한다.
-- 오류 SQLSTATE: NR001 = 3개 초과, NR002 = 이 워크스페이스에 없는 id(타 워크스페이스 포함).
-- updated_at은 바꾸지 않는다(편집 폼 낙관적 잠금 409 방지).

create function public.set_profile_selection(p_workspace uuid, p_ids uuid[])
returns uuid[]
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_ids uuid[];
  v_found integer;
begin
  -- 중복 제거(처음 나온 순서 유지)
  select coalesce(array_agg(s.x order by s.ord), '{}')
    into v_ids
    from (
      select distinct on (t.x) t.x, t.ord
      from unnest(coalesce(p_ids, '{}')) with ordinality as t(x, ord)
      order by t.x, t.ord
    ) s;

  if cardinality(v_ids) > 3 then
    raise exception '프로필은 최대 3개까지 선택할 수 있습니다' using errcode = 'NR001';
  end if;

  -- 같은 워크스페이스의 동시 선택 변경을 직렬화
  perform 1 from public.profiles p where p.workspace_id = p_workspace for update;

  select count(*) into v_found
    from public.profiles p
    where p.workspace_id = p_workspace and p.id = any (v_ids);
  if v_found <> cardinality(v_ids) then
    raise exception '없는 프로필 id가 포함되어 있습니다' using errcode = 'NR002';
  end if;

  update public.profiles p
    set selected = (p.id = any (v_ids))
    where p.workspace_id = p_workspace
      and p.selected is distinct from (p.id = any (v_ids));

  return v_ids;
end;
$$;
comment on function public.set_profile_selection(uuid, uuid[]) is
  '워크스페이스 프로필 선택을 원자적으로 갱신(최대 3, 빈 배열=전부 해제). API 전용';

revoke execute on function public.set_profile_selection(uuid, uuid[]) from public, anon, authenticated;
grant execute on function public.set_profile_selection(uuid, uuid[]) to service_role;
