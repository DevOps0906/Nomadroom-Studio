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
