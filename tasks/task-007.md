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
- [x] `cd apps/api && pytest -q tests/worker` 통과: 폐기 토큰 401·타 워크스페이스 job 404·중지된 job 409·201건 400·상태 전이 표 전 경로
- [x] 로그 캡처에 워커 토큰·쿠키 0건

## 구현 결정 (팀장, 2026-11-17 · challenger 검토 반영, ◆는 사람 결정 대상이라 기본값으로 정함)
- 상태 전이는 `docs/02_ARCHITECTURE.md#3-3`의 "수집 job 상태 전이" 표가 정본. 007이 맡는 것: W-01 claim(queued·retrying → running, 자기 running job 재반환), W-04(done·failed·stopped), 오프라인 지연 평가 함수(`app/jobs/state.py`, W-01·W-02에서 호출, 008이 A-05에서 재사용). A-05 stop·retry는 008.
- claim: RPC 없이 조건부 PATCH 1회(`workspace_id=토큰 ws&kind=eq.collect&status=in.(queued,retrying)`, `Prefer: return=representation`, 0행 → 204). select 후 update 금지. 동시 claim 2건 테스트.
- W-02~04: job.workspace_id = 토큰 워크스페이스 **그리고** `claimed_by = 현재 워커`. 아니면 404. heartbeat의 job_id도 같은 검증 후에만 `current_job_id`에 기록.
- ◆1 쓰기 범위에 `supabase/migrations/20261117000010_collect_apply.sql`·`supabase/tests/**` 추가: RPC `apply_collect_batch(p_workspace, p_job, p_worker, p_profile, p_payload jsonb)` — job이 running·collect·claimed_by=p_worker·profile이 job.profile_ids에 속함을 확인, 한 트랜잭션에서 candidates insert(on conflict do nothing, `first_job_id`), observations insert, candidate_verdicts insert, rep 갱신, `job_profile_runs.collected_count` 원자적 증가. service_role만 실행.
- W-03 순서: 형식 검증 → 요청 안 중복 제거 → 워크스페이스에 이미 있는 video_id 제외(=duplicates) → 남은 것만 할당량 예약 → videos.list → **YouTube가 돌려준 것만** RPC로 반영. 응답에서 빠진 영상은 버리고 `unavailable`로 셈. YouTube 실패·할당량 초과면 아무것도 넣지 않고 502·429(워커가 다시 보내도 duplicates가 되지 않음). 응답 `accepted`, `duplicates`, `unavailable`.
- duplicates = 요청 안 중복 + 워크스페이스에 이미 있는 후보(다른 프로필이 먼저 넣은 것 포함). 기존 후보에는 새 판정을 만들지 않는다(판정은 기록 검증에서).
- ◆3 워커 값 신뢰: YouTube 값으로 덮어쓰기 — title, channel_id, channel_title, license_cc, is_broadcaster(목록 대조), thumbnail_url(= `https://i.ytimg.com/vi/{video_id}/hqdefault.jpg`로 재구성, 워커 값 미사용). 워커 값 그대로 — market(KR·JP), format(short·long), category·genre(≤40자). 판정은 해당 profile로 `judge`(prev 없음 → 조건 제외 또는 no_prev).
- profile_id가 job.profile_ids에 없으면 400. job_profile_runs 행이 없으면 RPC가 생성(position = job.profile_ids 안 순서).
- ◆2 오프라인 지연 평가는 W-01·W-02(007)와 A-05 GET/POST(008)에서 호출.
- 입력 상한: 본문 1MB(워커 라우트 미들웨어), items ≤200(Field max_length — 201은 400), video_id `[A-Za-z0-9_-]{11}`, title ≤300, channel_title ≤200, 그 밖 문자열 ≤40, 제어 문자 거부.
- detail·error: 자유 문장 대신 코드 enum. chrome detail = `window_small`·`login_required`·`profile_locked`·`network`·`unknown`, W-04 error = `chrome_failed`·`vidiq_changed`·`network`·`stopped_by_user`·`unknown`. 화면이 한국어로 바꿔 표시. (04 W-02·W-04 행 갱신은 팀장)
- 쓰기 허용 확장: `apps/api/app/main.py`(include·미들웨어), `supabase/migrations/20261117000010_collect_apply.sql`, `supabase/tests/**`, `apps/web/src/types/db.ts`·`docs/diagrams/erd.*`(재생성). YouTube 클라이언트는 재사용만(수정 금지 — 필요하면 보고).

## 리뷰 반영 결정 (팀장, 2026-11-17 · code 리뷰)
- 오프라인 기준 시각 = `max(heartbeat.last_seen_at, job.started_at)`.
- claim 다중 행 우려: 활성 인덱스는 000005에서 queued·running·retrying으로 이미 확장됨 → 해당 없음. 그래도 PATCH에 order=created_at·limit 1 대신 테스트로 "queued+retrying 공존 불가"를 확인.
- claim 시 이전 실패 흔적(error·finished_at)은 비운다.
- 3-3의 3a("실패한 프로필 지점부터")를 따른다: RPC가 프로필 k의 후보를 처음 받을 때 position < k인 running 행을 done으로 올린다. job이 failed·stopped로 끝나면 running 행만 failed. 재시도 시작점 = position 순으로 첫 done 아닌 행(failed 또는 pending). 02#3-3 표의 job_profile_runs 문장도 이에 맞춘다(팀장).
- W-04 멱등: 이미 같은 워커가 같은 status로 끝낸 job에 W-04가 다시 오면 200(행 닫기 재시도). 다른 status면 409.

## 리뷰 반영 결정 (팀장, 2026-11-17 · security 리뷰, 🔴 포함)
- 🔴 job당 상한 강제: 새 마이그레이션 `20261117000011_collect_limits.sql`로 `jobs.lookup_count int not null default 0` 추가. RPC `reserve_collect_lookup(p_workspace, p_job, p_worker, p_n)`: job을 `for update`로 잠근 뒤 running·collect·claimed_by·`stop_requested=false`를 확인하고, `lookup_count + p_n ≤ params.limit(기본 200)`일 때만 더한다(아니면 NR005 → 409 "수집 상한 도달"). W-03은 할당량 예약 전에 호출한다. `apply_collect_batch`도 job의 누적 accepted(job_profile_runs.collected_count 합) + 신규 ≤ limit을 검사한다. → 탈취 토큰의 피해를 job 1건당 YouTube 조회 200건으로 제한한다(요청을 잘게 쪼개면 최대 200 unit = 일 상한의 2.5%). job은 사용자만 만들 수 있다(A-05).
- stop_requested=true면 W-03은 409(04 W-03 "409 중지됨"과 일치). 앞선 "중지 중에도 받음" 해석은 철회한다. RPC에도 같은 조건을 둔다.
- 제목: YouTube 제목이 비면 그 영상은 unavailable(워커 제목으로 대체하지 않음).
- 워커 문자열(genre·category): C0·DEL에 더해 C1(U+0080–009F), 방향 제어(U+202A–202E, U+2066–2069), 폭 없는 문자(U+200B–200D, U+FEFF), U+2028·2029도 거부한다(400).
- 인증 전 버퍼링: 본문 제한 미들웨어는 먼저 `Authorization: Bearer <uuid>.<secret>` 형식을 확인하고, 형식이 아니면 본문을 읽기 전에 401을 준다. 서버 수신 타임아웃·동시 연결 제한은 배포 체크 항목으로 둔다(팀장 기록).
- DB 방어선(000011): `jobs.error`, `job_profile_runs.detail`, `candidates.market`(KR·JP), `candidates.format`(short·long·null)에 check 제약을 둔다. 기존 행과 충돌하는지 확인한다.
- 잔여 위험(◆3 수용): market·category·format은 워커 값으로 판정에 들어간다. PRD#8 위협 메모의 "가짜 후보 주입" 행에 이미 있는 위험이며, job당 상한으로 범위를 제한한다.
- 테스트: 반복 W-03의 누적 상한 409, stop_requested 409, 제목 공백 unavailable, 금지 유니코드 400, 형식이 아닌 Authorization은 본문을 읽기 전에 401.
