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
- [x] `cd apps/api && pytest -q tests/collect_jobs` 통과: 멱등·409·재시도 상한·stop 후 후보 보존·타 워크스페이스 404
- [x] OpenAPI 출력이 `docs/04_API.md#A-05` 경로·메서드와 일치

## 007에서 넘어온 계약 (팀장, 2026-11-17)
- W-01은 `jobs.params`의 `resume_from_profile_id`·`limit`(기본·상한 200) 키를 읽는다. A-05 POST·retry는 이 키 이름으로 쓴다.
- 오프라인 지연 평가는 `app/jobs/state.py`의 `expire_offline_jobs(request, ws)`를 A-05 GET/POST 앞에서 호출한다. 상태 전이 정본은 `docs/02_ARCHITECTURE.md#3-3`.
- stop은 `stop_requested=true`만 켠다(running). queued·retrying은 즉시 stopped. retry는 failed에서 `retry_count`<3일 때 retrying.
- 재시도(A-05 retry) 시 `jobs.lookup_count`는 **초기화하지 않는다**(탈취 토큰의 반복 소진 방지). 대신 retry 응답·화면에 "이 작업의 조회 상한 도달 — 새 수집 실행" 안내. `params.limit`은 1~200 정수만 받는다.
- W-04 멱등 경합: retry는 재개 지점 이후의 failed 행을 pending으로 되돌린다(아래 구현 결정이 정본). 옛 W-04 재전송은 job이 retrying/running이라 409.
- 배포 체크: 워커 라우트 인증 전 1MB 버퍼링 → 프록시 연결·속도 제한 필수(작업 표 기록됨).

## 구현 결정 (팀장, 2026-11-17 · challenger 검토 반영, ◆는 사람 결정 대상이라 기본값으로 정함)
- 쓰기 허용 확장: `apps/api/app/main.py`(include), `supabase/migrations/20261117000012_collect_job_control.sql`, `supabase/tests/**`, `apps/web/src/types/db.ts`(재생성), `docs/04_API.md` A-05 행(팀장).
- GET·retry·stop 모두 `kind=collect`이고 워크스페이스가 같아야 한다. 아니면 404.
- retry RPC `retry_collect_job(p_workspace, p_job)`: job을 `for update`로 잠근 뒤 확인한다.
  - status=failed, retry_count<3, stop_requested=false여야 한다. 아니면 NR006 → 409 "재시도 불가".
  - ◆2 중지 요청 뒤 워커 오프라인으로 failed가 된 job은 retry를 막고, 화면에서 "새 수집 실행"으로 안내한다.
  - 조회 상한 도달(lookup_count ≥ limit 또는 sum(collected_count) ≥ limit)은 NR005 → 409 "이 작업의 조회 상한 도달 — 새 수집 실행".
  - 같은 워크스페이스에 다른 활성 collect job이 있으면 NR007 → 409.
  - 통과하면 retry_count+1, status=retrying, error·finished_at·claimed_by=null, `params.resume_from_profile_id` = position 순으로 처음 done이 아닌 프로필. 그 프로필과 이후 프로필의 failed 행은 pending으로 되돌린다(done 행은 유지).
- stop RPC `stop_collect_job(p_workspace, p_job)`: job을 잠근 뒤 처리한다.
  - queued·retrying이면 stopped로 바꾸고 error=`stopped_by_user`, finished_at=now.
  - running이면 stop_requested=true만 켠다.
  - done·failed·stopped이면 NR006 → 409 "이미 종료".
  - 응답은 실제 상태다(running+stop_requested 또는 stopped).
- 입력 `from_profile_id`는 없앤다(서버가 결정). retry·stop은 본문이 없다. 04 행을 이에 맞춘다.
- POST: profile_ids를 생략하면 selected 프로필을 쓴다.
  - ◆1 "조건 미설정" = 대상 프로필 0개 → 400.
  - 4개 이상이거나 다른 워크스페이스·없는 id가 섞이면 400.
  - jobs(kind=collect, status=queued, profile_ids, params{limit:200})를 만든 뒤 job_profile_runs(position 순, pending)를 만든다. runs 생성이 실패해도 W-02·RPC의 upsert가 보완한다.
- 멱등은 verify와 같다. 같은 키 확인을 활성 409보다 먼저 한다. 같은 키가 다른 kind면 409. 재요청은 200(새로 만들면 202). 23505는 제약 이름으로 구분한다.
- 429 `RATE_LIMITED`: 같은 워크스페이스에서 직전 collect job을 만든 지 60초 안에 새 키로 POST하면 거부한다.
- GET:
  - 먼저 `expire_offline_jobs`를 부른다.
  - `result{candidates, producible, pending}` = candidates 중 `first_job_id = job`인 것의 수와 rep_status별 수(used 제외). 기존 후보와 겹친 것은 포함하지 않는다.
  - `worker_last_seen_at`: claim한 워커가 있으면 그 워커 값, 없으면 이 워크스페이스에서 폐기되지 않은 워커 중 최댓값, 워커가 없으면 null. `worker_online` = 3분 이내.
- 테스트: OpenAPI(`api_docs_enabled=True` 설정으로 `app.openapi()`)의 A-05 경로·메서드·202가 04와 일치하는지 확인한다. stop과 claim 경합, retry 두 번 동시, 다른 kind id는 404.

## 리뷰 반영 결정 (팀장, 2026-11-17)
- 60초 제한의 비원자 경합(동시 다른 키·즉시 중지 직후)은 수용: 추가 피해는 job 1건(조회 ≤200). 대신 **워크스페이스당 최근 24시간 collect job 생성 20건 상한** → 429 `RATE_LIMITED`(상수).
- profile_ids 생략 경로도 대상이 3개를 넘으면 400.
- 000012(커밋 전): params.limit 판정을 중첩 CASE로(문자열이어도 22P02 없이 기본 200).
- 테스트: 실제 DB 통합 테스트에 retry 경로(POST → claim → W-04 failed → retry → 재수령·resume 확인) 추가, 동시 다른 키 POST 경합, 일 상한 429, Idempotency-Key 101자·제어 문자·비ASCII 400, OpenAPI에 retry·stop 200 확인.
