# task-008 수집 작업 API A-05 (collect-jobs)

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-007 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (실행류 POST·멱등·남용 방지) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-05`, `docs/02_ARCHITECTURE.md#3-1·#3-3`, `docs/05_DATA_MODEL.md#jobs·job_profile_runs`, `docs/01_PRD.md#8` |
| 쓰기 허용 | `apps/api/app/routes/collect_jobs.py`, `apps/api/tests/collect_jobs/**` |

## 할 것
- `POST /v1/collect-jobs`(202, `Idempotency-Key`, 조건 없음·3개 초과 400, 진행 중 409), `GET /{id}`(chrome_state·`worker_last_seen_at`), `POST /{id}/retry`(실패 프로필부터, 상한 초과 409), `POST /{id}/stop`(`stop_requested`).
- 워크스페이스당 동시 1건, 같은 키 재요청은 기존 job 반환.

## 하지 않을 것
- 예약 실행, 웹 화면, 워커 측 로직.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/collect_jobs` 통과: 멱등·409·재시도 상한·stop 후 후보 보존·타 워크스페이스 404
- [ ] OpenAPI 출력이 `docs/04_API.md#A-05` 경로·메서드와 일치
