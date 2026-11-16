# task-006 YouTube 관측 서비스 · A-07 기록 검증 · 할당량 방어선

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-005 |
| 위험도 | 높음 |
| 보안 영향 | 키·권한 · 노출 면 (YouTube API 키, 실행류 POST) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-07`, `docs/adr/0002-observation-quota.md`, `docs/01_PRD.md#7(Q3)·#8`, `docs/02_ARCHITECTURE.md#3-2`, `docs/05_DATA_MODEL.md#observations·jobs` |
| 쓰기 허용 | `apps/api/app/youtube/**`, `apps/api/app/routes/verify_runs.py`, `apps/api/tests/youtube/**` |

## 할 것
- `videos.list`(50개 묶음)·`channels.list`만 사용하는 클라이언트(`search.list` 호출 금지), 응답을 observations(추가 전용)로 기록.
- 직전 관측 24시간 미만은 건너뜀(`skipped_recent`), 간격 24시간~7일, 후보 상한 200.
- 일 사용량 기록, 8,000 unit 초과 시 중지 → 429 `QUOTA_EXCEEDED`(이전 판정 유지).
- `POST /v1/verify-runs`: `Idempotency-Key`, 동기 응답, 동시 1건(409). 키는 서버 환경변수만.

## 하지 않을 것
- vidIQ 수치를 판정 근거로 쓰기, 워커 호출, 키를 로그·응답에 노출.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/youtube`(YouTube 응답은 목) 통과: 재요청 멱등·방어선 초과 429·500건 → 호출 수 상한
- [ ] 코드 검색 `grep -rn "search.list\|/search" apps/api/app` 0건
- [ ] 로그 캡처에 API 키 0건
- [ ] 실제 단가·한도는 콘솔 재확인 필요(`미확인`) — 상수로 분리

## 구현 결정 (팀장, 2026-11-16 · challenger 검토 반영, ◆는 사람 결정 대상이라 기본값으로 정함)
- 쓰기 허용 확장: `app/config.py`(YOUTUBE_API_KEY SecretStr·상수), `app/main.py`(include), `app/logging_mask.py`(키 패턴), `.env.example`(이름만, `cat >>`), `supabase/migrations/20261116000009_verify_quota_apply.sql`, `supabase/tests/**`, `apps/web/src/types/db.ts`·`docs/diagrams/erd.*`(재생성).
- 키 전송: 쿼리 `key=` 대신 헤더 `X-Goog-Api-Key`. 마스킹에 `AIza[0-9A-Za-z_-]{35}`·`key=\S+` 추가. 실제 예외 경로(httpx HTTPStatusError + errors.py exc_info) 캡처 테스트에서 키 0건.
- 할당량: 테이블 `api_quota_daily(day date PK, units int)` — **서버 전체 1개 카운터**(키가 하나), 일자는 `America/Los_Angeles` 기준(YouTube 리셋). RPC `reserve_quota(p_units int, p_limit int) returns boolean`이 원자적으로 `units + p_units ≤ p_limit`일 때만 더한다. **호출 전에 예약**, 실패한 호출도 소진으로 본다(보수적). 상한 8,000(상수). 예약 실패 또는 YouTube 403 `quotaExceeded` → 429 `QUOTA_EXCEEDED`. RLS on·정책 없음·service_role만 execute/select.
- channels.list 쓰지 않음. videos.list(part=snippet,statistics,status) 1 unit/50개만. `search` 경로 0건.
- 대상(◆1): 워크스페이스 후보 중 **used=false**(◆3: 사용한 소재는 관측 안 함), 최신 관측이 없거나 24시간 이상 지난 것, `latest_observed_at asc nulls first, id` 순으로 최대 200. 24시간 미만은 `skipped_recent`. 판정 프로필은 profile_ids(없으면 selected). 선택 해제된 프로필의 기존 판정은 그대로 둔다.
- 대표 판정(◆2): 새 판정 + 그 후보의 기존 판정 전체로 `pick_representative`, 프로필 순서는 name asc(011 profile_names와 동일).
- YouTube 값 반영: license_cc = `status.license == 'creativeCommon'`, channel_id·channel_title은 snippet 값으로 갱신, is_broadcaster는 YouTube channelId를 broadcaster_channels와 대조해 다시 계산. 응답에서 빠진 영상(삭제·비공개)은 관측 없음 → `failed`로 센다(굶주림 위험은 작업 표에 기록).
- 원자성: 50개 묶음마다 RPC `apply_verify_batch(p_workspace, p_job, p_payload jsonb)` 한 번 — 한 트랜잭션에서 observations insert(서버가 uuid 생성), candidate_verdicts upsert, candidates 갱신(rep_status·rep_profile_id·status_changed_at(상태 바뀔 때만)·license_cc·channel·is_broadcaster). 실패한 묶음만 이전 판정 유지.
- job: 시작 전 같은 워크스페이스의 `verify` running/queued 중 started_at(또는 created_at)이 10분 넘은 것은 `failed`(error='timeout')로 정리. insert는 status=running. 끝나면 done(result: checked·skipped_recent·failed·counts) 또는 failed(중간 429·502, 이미 반영된 묶음은 유지). 오류 응답은 공통 형식만.
- 멱등: 같은 워크스페이스·같은 키의 job이 있으면 kind가 다를 때 409, 같으면 그 job 반환(running이면 status만, done이면 result 그대로). 본문이 달라도 기존 job 반환(문서화). 23505는 제약 이름으로 구분: 멱등 키 → 기존 job 조회 후 반환, 활성 job 인덱스 → 409 "검증 진행 중".
- counts: A-04와 같은 정의(필터 없음), 011의 `candidate_list_v` 사용(011 커밋 후 착수).
- 상수(가정·콘솔 재확인 필요 `미확인`): 단가 videos.list 1, 상한 8,000, 묶음 50, 후보 200, 정리 시간 10분 — `app/youtube/constants.py`.
