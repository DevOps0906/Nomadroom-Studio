# task-019 YouTube 검색 후보 수집 (vidIQ 대체)

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-006, task-008, task-013 |
| 위험도 | 높음 (→ 워커 model: opus) |
| 보안 영향 | 키·권한 · 노출 면 (YouTube API 키·할당량, 실행류 POST) |
| 담당 | builder + tester |
| 근거 | `docs/adr/0002-observation-quota.md`(2026-11-17 결정), `docs/01_PRD.md#7`(Q3)·`#9`, `docs/04_API.md#A-05`, `docs/02_ARCHITECTURE.md#3-1·#3-3`, `tasks/task-006.md#구현 결정`·`task-007.md#구현 결정` |
| 쓰기 허용 | `apps/api/app/youtube/**`, `apps/api/app/routes/collect_jobs.py`, `apps/api/app/collect/**`, `apps/api/tests/**`, `supabase/migrations/<새 번호>_*.sql`, `supabase/tests/**`, `apps/web/src/components/monitoring/**`, `docs/04_API.md`(팀장), `docs/adr/0002-observation-quota.md`(상태만), `apps/api/app/routes/worker.py`(W-01 claim 배제만), `apps/api/app/jobs/**`(만료 배제만) |

## 할 것 (사용자 결정 2026-11-17: A안)
- 후보 발굴을 서버에서 YouTube `search.list`로 한다(워커 불필요). 프로필 조건 → 검색 파라미터(시장→regionCode·relevanceLanguage, 형식→videoDuration, 키워드→q, maxResults 50) → 결과 video_id로 `videos.list` 1차 관측 → 판정(prev 없음) → 후보·관측·판정 저장.
- 할당량: 검색 전용 일 상한 2,000 unit(상수) + 전체 방어선 8,000 unit(`reserve_quota`) 둘 다 원자적으로 예약. 초과 시 429 `QUOTA_EXCEEDED`.
- 수집 job 모델 재사용(kind=collect, `params.source = "youtube_search"`), 상태 전이는 `02#3-3`과 일치(서버가 동기 처리 후 done·failed). 멱등·60초·24시간 20건 상한 그대로.
- 화면: 검색 수집일 때 Chrome 준비 결과·워커 오프라인 안내는 숨기고 "vidIQ 수집: 준비 중" 안내만 표시.

## 하지 않을 것
- vidIQ 자동화(task-009, 준비 중), 예약 실행, 검색 결과의 vidIQ 수치 사용.

## 완료 조건 (실행 가능한 확인)
- [x] `cd apps/api && pytest -q` 통과(YouTube 목): 검색 파라미터 매핑, 검색 일 상한·전체 방어선 429, 중복 후보 제외, 응답에서 빠진 영상 제외, 키 로그 0건
- [x] `grep -rn "search.list\|/search" apps/api/app`는 `app/youtube/` 안 1곳만
- [x] web `pnpm typecheck && pnpm lint && pnpm test` 통과, /monitor 캡처
- [ ] 단가·한도는 콘솔 재확인 필요(`미확인`) — 상수로 분리

## 착수 결정 (팀장, 2026-11-18 challenger 반영)
- 저장: 워커용 RPC(`apply_collect_batch`·`reserve_collect_lookup`)는 건드리지 않는다. 서버 전용 새 RPC(예: `apply_search_batch`, service_role만 실행, worker 인자 없음)를 새 마이그레이션으로 만들고 중복 제거·후보·관측·판정 저장 로직을 그 안에서 재사용한다.
- job 수령 배제: 검색 job은 `status=running`·`started_at`·`params.source='youtube_search'`로 바로 만든다. W-01 claim은 `params->>source='youtube_search'`를 제외한다. 기존 retry RPC는 검색 job을 거부하고, 검색 재시도는 서버가 `failed → running`으로 직접 바꿔 같은 요청 안에서 다시 실행한다(`retrying` 상태와 `claimed_by` 사용 안 함). stop은 검색 job에 409.
- 오프라인 만료 배제: `expire_offline_jobs`는 검색 job을 제외한다. 대신 서버 중단 대비로 running 5분 초과 검색 job은 `upstream_error`로 실패 처리한다. 동기 처리는 verify의 `except BaseException` 정리 패턴을 따른다. jobs.error check에 `upstream_error`·`quota_exceeded`가 없으면 새 마이그레이션에서 추가한다.
- 계약: A-05 응답(`CollectJobOut`·상세·활성)에 `source: "vidiq" | "youtube_search"`를 추가한다. web `job.ts`도 이 필드를 받는다. 04_API A-05 행과 공통 규칙의 "search.list 금지"를 고치고, ADR 0002 상태를 "승인"으로 바꾼다(이 작업에서 팀장이 한다).
- 검색 파라미터: `type=video`·`part=id`·`maxResults=50`·`order=viewCount`, publishedAfter 없음. 시장 → regionCode·relevanceLanguage. 키워드가 있으면 q = 키워드를 ` | `로 묶은 OR, 없으면 q 없이 검색한다(판정이 걸러냄). 형식이 shorts면 `videoDuration=short`, long이면 videoDuration을 지정하지 않는다. 형식은 `videos.list`에 `contentDetails`를 더해 실측 길이로 정하고(같은 1 unit), 180초 이하를 shorts로 본다. 프로필 형식과 다르면 판정의 `format`으로 제외한다. category는 W-03과 같은 규칙을 쓴다.
- 겹친 영상: 이번 실행의 모든 프로필로 판정하고, 대표 판정은 PRD#9 순서4를 따른다.
- 할당량: job을 만들기 전에 (실행 프로필 수 × 100)을 검색 상한 2,000과 전체 방어선 8,000에 한 번에 원자적으로 예약한다. 초과하면 429 `QUOTA_EXCEEDED`, job은 만들지 않는다. videos.list 관측분은 기존 `reserve_quota`를 쓴다. 실패한 프로필의 unit은 돌려받지 않는다(수용). 재시도는 남은 프로필만 다시 예약해 실행한다(`resume_from_profile_id`).
- 비신뢰 응답: 검색 응답 id는 `VIDEO_ID_RE`로 거른 뒤에만 PostgREST 필터에 넣는다(테스트 포함).
- 검증: pgTAP으로 예약 경계(2,000·8,000 동시)·동시 예약 원자성·W-01 claim 배제·retry/stop 거부를 확인한다.
- 사람 결정 아님(팀장): 검색 상한 2,000은 서버 공용이다. PRD#6이 단일 워크스페이스(다중 워크스페이스 MVP 제외)이므로 받아들이고 `발견한 문제`에 기록한다.

## 리뷰 반영 결정
- reviewer security ACCEPT, code+contract REQUEST_CHANGES → 반영: 웹 수집·재시도 타임아웃 60초(🔴), 서버 처리 상한(YouTube 호출 6초·실행 마감 40초), 할당량 환불 `release_search_quota`, 검색 retry 60초 제한, `apply_search_batch` 소속 검사를 실제로 쓰는 프로필로 좁힘(000014).
- category·market은 찾은 프로필 값(검색 결과에 자체 분류 없음). 시작 후 실패는 202 + failed job(04 A-05 반영).
- release는 그 시점 날짜 행에서 뺀다(자정 경계 드문 오차 수용). 웹 DB 타입 재생성.
- 검증: api pytest 515 + integration 13, supabase test db 275, web 274, /monitor 3구간 캡처(임시 running 검색 job으로 패널 확인 후 삭제).
