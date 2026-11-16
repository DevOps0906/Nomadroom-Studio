# task-011 조회 API A-02 · A-04 · A-06

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-005, task-010 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (인증 후 조회 API, 워크스페이스 격리) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-02·A-04·A-06`, `docs/05_DATA_MODEL.md#candidates·candidate_verdicts·observations`, `docs/01_PRD.md#3·#9` |
| 쓰기 허용 | `apps/api/app/routes/dashboard.py`, `apps/api/app/routes/candidates.py`, `apps/api/tests/read_api/**` |

## 할 것
- `GET /v1/dashboard/summary`(미연동 3칸은 null), `GET /v1/candidates`(상태·카테고리·형식·프로필·라이선스·검색·정렬·페이지, counts 포함), `GET /v1/candidates/{id}/evidence`.
- 표시 상태는 `used`가 판정보다 우선. 모든 쿼리 `workspace_id` 조건.

## 하지 않을 것
- A-08(task-017), 저장된 보기, 쓰기 로직.

## 완료 조건 (실행 가능한 확인)
- [x] `cd apps/api && pytest -q tests/read_api` 통과: 필터·정렬·페이지(size 61 → 400 또는 60 제한), counts 합계, 타 워크스페이스 404, 이전 관측 없음 `needs_prev`

## 구현 결정 (팀장, 2026-11-16 · challenger 검토 반영)
- **목록 뷰** `public.candidate_list_v`(새 마이그레이션 `20261116000008_candidate_list_view.sql`, `security_invoker = true`): candidates + 대표 판정(`candidate_verdicts.profile_id = candidates.rep_profile_id`) + 그 판정의 prev/curr observations. 열: 후보 열 + `display_status`, `growth_pct`, `prev_observed_at`·`prev_view_count`, `curr_observed_at`·`curr_view_count`, `reason`, `latest_observed_at`(후보의 최신 관측). select는 service_role만(anon·authenticated revoke). pgTAP: 뷰 권한, display_status 규칙, 시드 5건 값.
- `display_status`: used=true → `used`, 아니면 `coalesce(rep_status, 'pending')`(판정 전 후보는 근거 대기로 봄).
- counts: status 필터를 뺀 나머지 필터(category·format·profile_id·license·q)를 반영. producible·pending·excluded는 used 제외, used는 따로. **total = 네 값의 합**. 상태별 count=exact HEAD 요청.
- 정렬: `growth` = growth_pct desc nullslast, `views` = curr_view_count desc nullslast, `recent` = created_at desc(기본). 모든 정렬에 tie-breaker id asc. page ≥1, size 1~60(기본 24), **61 이상은 400**.
- q: 앞뒤 공백 제거, 1~100자, 제어 문자 400. PostgREST `or=(title.ilike."*…*",channel_title.ilike."*…*")`. 값은 큰따옴표로 감싸고 `\`·`"`는 이스케이프, `%`·`_`·`*`는 리터럴로 이스케이프. PostgREST 4xx 응답은 400 VALIDATION(field q)이 아니라 미리 막는다(나머지는 503).
- category 필터와 `categories[]`는 `category` 열(genre 아님). categories는 워크스페이스 후보의 category를 받아 중복을 지우고 가나다순으로 정렬. null은 제외.
- profile_id: 해당 프로필의 판정이 있는 후보(상태 무관). item 값은 대표 판정 기준. `profile_names[]`는 판정이 excluded가 아닌 프로필 이름(프로필 position 순서는 아직 없으니 name 순).
- license: `cc` = license_cc=true, `any` = 필터 없음.
- period_days: prev·curr 간격(일), 소수 첫째 자리 반올림(ROUND_HALF_UP), prev 없으면 null.
- next_observation_at: display_status=pending일 때만 `latest_observed_at + 24h`(UTC ISO, 과거여도 그대로, 화면이 "지금 가능"으로 표시). 관측 없으면 null.
- A-06: 대표 판정이 없거나 curr가 정리됨 → 200, prev·curr null, needs_prev=true, reason null. 타 워크스페이스·없는 id는 404.
- A-02: 기간은 now 기준 rolling(24h·7d). collected = 기간 내 created_at 건수. stealth{producible, pending} = 현재 전체(used 제외, 기간 무관). recent_ready = display_status=producible이면서 status_changed_at이 기간 내인 것, 최신순 5건(rep 프로필 이름 포함).
- thumbnail_url: API에서 `https://i.ytimg.com/`로 시작하지 않으면 null로 내보냄(비신뢰 데이터 규칙의 1차 방어, 웹도 이미지 허용 목록).
- 모든 쿼리에 workspace_id 조건(뷰·verdicts·observations·profiles 모두). 시각은 UTC ISO 8601.
- 쓰기 허용 확장: `apps/api/app/main.py`(include), `supabase/migrations/20261116000008_*`, `supabase/tests/**`, `apps/web/src/types/db.ts`·`docs/diagrams/erd.*`(재생성만), `docs/04_API.md` A-02·A-04·A-06 행(팀장).
