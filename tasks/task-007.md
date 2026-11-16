# task-007 워커 API W-01~W-04 · job 상태

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-006 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 · 키·권한 (워커 토큰 인증 엔드포인트) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#워커 API`, `docs/02_ARCHITECTURE.md#3-1·#3-3`, `docs/05_DATA_MODEL.md#jobs·job_profile_runs·worker_heartbeats`, `docs/01_PRD.md#8`, `docs/adr/0001-worker-location.md` |
| 쓰기 허용 | `apps/api/app/routes/worker.py`, `apps/api/app/jobs/**`, `apps/api/tests/worker/**` |

## 할 것
- W-01 claim(204 포함, 자기 워크스페이스 큐만) · W-02 heartbeat(`stop_requested` 반환) · W-03 후보 접수(≤200, 형식 검증·중복 제거·1차 관측·근거 대기 판정) · W-04 finish.
- job 상태 전이(`queued→running→retrying/stopped/failed/done`)와 워커 오프라인 시 failed 처리 — 02#3-3 그대로.
- 워커 입력은 신뢰하지 않음: Pydantic 형식 검증, 썸네일 `i.ytimg.com`만, 오류 메시지에 쿠키·경로 금지.

## 하지 않을 것
- 사용자용 `/v1/collect-jobs`(task-008), 워커 구현(task-009), 워커에 DB 접속 정보 제공.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/worker` 통과: 폐기 토큰 401·타 워크스페이스 job 404·중지된 job 409·201건 400·상태 전이 표 전 경로
- [ ] 로그 캡처에 워커 토큰·쿠키 0건
