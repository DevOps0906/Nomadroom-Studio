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

## 007에서 넘어온 계약 (팀장, 2026-11-17)
- W-01은 `jobs.params`의 `resume_from_profile_id`·`limit`(기본·상한 200) 키를 읽는다. A-05 POST·retry는 이 키 이름으로 쓴다.
- 오프라인 지연 평가는 `app/jobs/state.py`의 `expire_offline_jobs(request, ws)`를 A-05 GET/POST 앞에서 호출한다. 상태 전이 정본은 `docs/02_ARCHITECTURE.md#3-3`.
- stop은 `stop_requested=true`만 켠다(running). queued·retrying은 즉시 stopped. retry는 failed에서 `retry_count`<3일 때 retrying.
- 재시도(A-05 retry) 시 `jobs.lookup_count`는 **초기화하지 않는다**(탈취 토큰의 반복 소진 방지). 대신 retry 응답·화면에 "이 작업의 조회 상한 도달 — 새 수집 실행" 안내. `params.limit`은 1~200 정수만 받는다.
- W-04 멱등 경합: 사용자 retry가 job을 retrying으로 바꿀 때 `job_profile_runs`의 failed 행은 그대로 두고, 재수령 뒤 새 running 행만 생기게 한다(옛 W-04 재전송은 status가 달라 409).
- 배포 체크: 워커 라우트 인증 전 1MB 버퍼링 → 프록시 연결·속도 제한 필수(작업 표 기록됨).
