# 05 데이터 모델 — Nomadroom Studio

> ERD: [`diagrams/erd.mmd`](diagrams/erd.mmd) — `sql2erd supabase/migrations -o docs/diagrams/erd.mmd` 로 생성(손으로 그리지 않음)
> 근거: `02_ARCHITECTURE.md#2`(쓰기는 API service_role만) · `01_PRD.md#8` · `01_PRD.md#9`(판정 규칙·reason 코드). 마이그레이션 SQL은 구현 작업에서 만든다.

## 공통 규칙
- 모든 테이블 RLS 켬. 소유 키 `workspace_id`(MVP는 워크스페이스 1개이나 모든 행에 둔다). 시간은 `timestamptz`(UTC 저장, KST 표시). PK는 `uuid`.
- 헬퍼 `is_workspace_member(ws uuid)` = `workspace_members`에서 `auth.uid()` 소속 확인. 아래 "읽기"는 `authenticated` + 이 함수. 브라우저(anon 키+사용자 JWT)는 **읽기만**, 쓰기는 정책 없음(= 거부) → API(service_role)만 쓴다. `saved_views`는 이후(`01_PRD.md#3`)라 MVP 테이블 없음.
- 컬럼 이름이 `04_API.md` 출력 필드와 같다(별칭은 04에 표시). 수치 범위(증가율·키워드 개수 등)는 가정.

## 테이블
| 테이블 | 목적 | 주요 컬럼 | RLS 기준 | 비고 |
|---|---|---|---|---|
| workspaces | 워크스페이스(MVP 1개) | id, name, created_at | 읽기: 구성원. 쓰기 없음 | 시드로 1행 |
| workspace_members | 사용자-워크스페이스 소속 | workspace_id, user_id(→auth.users), role(`owner`·`member`) , created_at | 읽기: 본인 행만. 쓰기 없음 | 이후 다중 워크스페이스·역할 확장. PK(workspace_id, user_id) |
| profiles | 프로필별 수집 조건 | id, workspace_id, name, market, format(`all`·`short`·`long`), category, min_views(int ≥0), max_growth_pct(허용 증가율, numeric 0~1000 가정), keywords(text[] ≤5개 가정), cc_only(bool), include_broadcast(bool), selected(bool, 검증 대상 체크), updated_at | 읽기: 구성원. 쓰기: API만(Pydantic 검증) | 워크스페이스당 selected 최대 3(API가 강제). `market` 허용 값: MVP는 `KR`·`JP`(팀장 결정 2026-11-16), 추가는 이후 |
| broadcaster_channels | 방송사 목록(Q2 확정) | id, workspace_id, channel_id, channel_title, created_at | 읽기: 구성원. 쓰기: API만 | unique(workspace_id, channel_id). 목록에 있으면 `candidates.is_broadcaster`=true, 없으면 false("방송사 아님", 미확인 없음). 관리 화면은 MVP 밖 → 초기 시드는 구현 작업에서 |
| candidates | 수집된 후보 영상(영상 단위 1행) | id, workspace_id, video_id, title, thumbnail_url, genre, category, format, market, channel_id, channel_title, license_cc(bool·null=미확인), is_broadcaster(bool), used(bool, 수동 표시, Q4 제안), used_at, rep_status(`producible`·`pending`·`excluded`), rep_profile_id, status_changed_at, first_job_id, created_at | 읽기: 구성원. 쓰기: API만(`used`도 API 경유) | unique(workspace_id, video_id)로 중복 제거. 표시 상태: `used`=true면 판정보다 우선 |
| observations | 시점별 관측값(조회수 등) | id, workspace_id, candidate_id, observed_at, view_count(bigint), license_cc, channel_id, source(`youtube_api`), job_id | 읽기: 구성원. 쓰기: API만, **추가 전용**(수정 없음). 180일 초과분만 정리 삭제(가정, `01_PRD.md#8`) | index(candidate_id, observed_at desc). 판정은 직전 관측 ≥24시간 간격만 새로 기록(간격 24시간~7일) |
| candidate_verdicts | 프로필별 판정 + 근거 | id, workspace_id, candidate_id, profile_id, status(`producible`·`pending`·`excluded`), reason(코드 정본 `01_PRD.md#9`), growth_pct(numeric·null), prev_observation_id, curr_observation_id, judged_at | 읽기: 구성원. 쓰기: API만 | unique(candidate_id, profile_id) 최신 1행 덮어씀(이력은 observations). 대표 판정은 `candidates.rep_status`에 반영(제작 가능 > 근거 대기 > 첫 프로필) |
| jobs | 작업 큐(수집·검증 실행) | id, workspace_id, kind(`collect`·`verify`), status(`queued`·`running`·`retrying`·`stopped`·`failed`·`done`), profile_ids(uuid[]), params(jsonb: 후보 상한 등), idempotency_key, retry_count(상한 `02_ARCHITECTURE.md#3-3`), stop_requested(bool), requested_by, claimed_by(→workers), result(jsonb: 후보 수·제작 가능 N·근거 대기 N·건너뜀·실패 사유), error, created_at, started_at, finished_at | 읽기: 구성원. 쓰기: API만(워커는 API 경유) | unique(workspace_id, idempotency_key). 같은 kind `queued`·`running`은 워크스페이스당 1개(409). 상태 전이 `02_ARCHITECTURE.md#3-3`. 03의 `collect_runs`는 이 테이블 |
| job_profile_runs | 작업 안의 프로필별 진행·Chrome 준비 상태 | id, workspace_id, job_id, profile_id, position(순서), chrome_state(`ready`·`resize_needed`·`login_needed`·`error`), detail(원인 문구, 쿠키·경로 금지), collected_count, status(`pending`·`running`·`done`·`failed`), updated_at | 읽기: 구성원. 쓰기: API만 | unique(job_id, profile_id). "해당 후보부터 재시도"는 `failed` 프로필의 position부터 |
| workers | 수집 워커 등록·토큰 | id, workspace_id, name, token_hash(해시만), revoked_at, created_at | **일반 사용자 접근 없음**(정책 없음 = 전부 거부). API만 읽기·쓰기 | 토큰 원문은 PC에만. 워크스페이스 범위. 발급·폐기·회전은 운영 절차(화면 없음, 회전 90일 가정, `01_PRD.md#8`) |
| worker_heartbeats | 워커 생존·현재 작업 | worker_id(PK), workspace_id, last_seen_at, current_job_id, chrome(jsonb: 프로필별 state 요약) | 읽기: 구성원. 쓰기: API만 | 워커당 1행 upsert. `last_seen_at` 오프라인 기준·job `failed` 처리는 `02_ARCHITECTURE.md#3-3` |
