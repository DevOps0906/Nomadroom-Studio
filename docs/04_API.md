# 04 API — Nomadroom Studio

> 근거: `03_SCREENS_UX.md`(API ID) · `02_ARCHITECTURE.md#2·#3`(웹 Route Handler → FastAPI, `Authorization: Bearer <Supabase 사용자 JWT>`) · `01_PRD.md#8` · 컬럼은 `05_DATA_MODEL.md`.
> 출력 필드 이름 = 05 컬럼 이름. 별칭·계산 값은 `(←테이블.컬럼)`으로 출처 표시. 브라우저는 API를 직접 부르지 않는다(웹 서버 중계).

## 공통 규칙
| 항목 | 내용 |
|---|---|
| 기준 경로·형식 | `/v1/...` JSON. 시각은 ISO 8601 UTC(화면에서 KST 변환). 목록은 `page`·`size`(기본 24, 최대 60 — 가정) |
| 권한 | "로그인" = JWT 서명·만료 검증 + `workspace_members` 소속. 워크스페이스는 JWT로 결정(입력으로 받지 않음) |
| 멱등 | 실행류 POST는 `Idempotency-Key` 헤더 필수(`jobs.idempotency_key`). 같은 키 재요청은 기존 job 반환 |
| 오류 형식 | `{code, message, field?}`. 키·토큰·쿠키·내부 경로는 메시지에 넣지 않는다 |
| 공통 오류 | 400 `VALIDATION`(필드별) · 401 `UNAUTHENTICATED` · 403 `FORBIDDEN`(소속 없음. 타 워크스페이스 리소스는 404) · 404 `NOT_FOUND` · 409 `CONFLICT` · 429 `RATE_LIMITED`·`QUOTA_EXCEEDED` · 405 `METHOD_NOT_ALLOWED` · 500 `INTERNAL` · 502 `UPSTREAM_ERROR`(YouTube) · 503 `UPSTREAM_ERROR`(Supabase 인증 키·DB 조회 실패) |
| 상한(가정) | 실행당 후보 200(`01_PRD.md#7` Q3) · 검증 대상 프로필 최대 3 · YouTube 조회 `videos.list` 50개/호출(`search.list` 금지) · 재시도 상한·워커 오프라인 기준은 `02_ARCHITECTURE.md#3-3` |

## 사용자 API (웹 → FastAPI)
| ID | 메서드 | 경로 | 입력 | 출력 | 권한 | 오류 |
|---|---|---|---|---|---|---|
| A-01 | (Supabase Auth, FastAPI 아님) | `signInWithPassword` · `resetPasswordForEmail` | email, password | 세션(서버 쿠키 httpOnly). 사용자 `auth.users.email` | 비로그인 | 400 자격 불일치(입력 유지) · 429 시도 제한 |
| A-02 | GET | `/v1/dashboard/summary` | `period`(`24h`·`7d`, 기본 `7d`) | `stats.collected`(←`candidates` 건수), `stats.in_progress`·`reviewed`·`upload_pending`(MVP: 항상 null → 화면 "—"+"운영 사이트 연동 전"), `stealth{producible, pending}`(←`candidates.rep_status`), `recent_ready[≤5]{id,title,profile_name,growth_pct,status_changed_at}`(←`candidates`·`candidate_verdicts`, 기간 내 제작 가능 판정), `updated_at` | 로그인 | 401 |
| A-03 | GET | `/v1/profiles` | — | `items[]{id, name, market, format, category, min_views, max_growth_pct, keywords, cc_only, include_broadcast, selected, updated_at}`(←`profiles`) | 로그인 | 401 |
| A-03 | PUT | `/v1/profiles/{id}` | 조건 필드(`market`·`format`·`category`·`min_views`·`max_growth_pct`·`keywords`·`cc_only`·`include_broadcast`) + `updated_at`(낙관적 잠금). `name`·`selected`는 받지 않음. 범위: `min_views` 0~2,000,000,000, `max_growth_pct` 0~1000, `keywords`≤5개·각 1~30자(가정), `category` ≤40자(빈 값·`전체`=조건 없음) | 저장된 프로필 1건(`profiles`) | 로그인 | 400 필드별 · 404 · 409 동시 수정(`updated_at` 불일치) |
| A-03 | PUT | `/v1/profiles/selection` | `selected_ids[]`(최대 3) | `selected_ids[]` (←`profiles.selected`, 원자적 갱신·빈 배열=전부 해제) | 로그인 | 400 3개 초과·없는 id(타 워크스페이스 포함) |
| A-04 | GET | `/v1/candidates` | `status`(`all`·`producible`·`pending`·`excluded`·`used`), `category`, `format`, `profile_id`, `license`(`cc`·`any`), `q`(제목·채널), `sort`(`growth`·`views`·`recent`), `page`, `size` | `counts{total, producible, pending, excluded, used}`, `categories[]`, `items[]{id, thumbnail_url, status(←`rep_status`, `used`면 `used`), genre, title, format, profile_names[], license_cc, prev{observed_at, view_count}, curr{observed_at, view_count}, growth_pct, period_days, next_observation_at(근거 대기만), used}`, `updated_at` | 로그인 | 400 파라미터(size 61 이상·page 1001 이상·q 100자 초과·제어 문자, 공백뿐인 q는 필터 없음). 규칙: counts는 status 외 필터 반영·total=네 상태 합, 판정 전 후보는 `pending`, 정렬 tie-breaker id, 썸네일은 `i.ytimg.com`만(아니면 null). 상세 `tasks/task-011.md#구현 결정` |
| A-05 | POST | `/v1/collect-jobs` | `Idempotency-Key`, `profile_ids[]`(생략 시 선택된 프로필). 조건 미설정이면 거부 | `job{id, status, profiles[]{profile_id, chrome_state, status, collected_count}}`(202, ←`jobs`·`job_profile_runs`) | 로그인 | 400 조건 없음·3개 초과 · 409 수집 진행 중 · 429 |
| A-05 | GET | `/v1/collect-jobs/{id}` | — | `job{id, status, error, result{candidates, producible, pending, ...}, profiles[]{profile_id, chrome_state, detail, status, collected_count}, worker_last_seen_at(←`worker_heartbeats.last_seen_at`)}` | 로그인 | 404 |
| A-05 | POST | `/v1/collect-jobs/{id}/retry` | `from_profile_id`(실패한 프로필) | `job`(`retrying`→`running`, 수집된 후보 유지) | 로그인 | 404 · 409 재시도 불가 상태·상한 초과(`02_ARCHITECTURE.md#3-3`) |
| A-05 | POST | `/v1/collect-jobs/{id}/stop` | — | `job{status:"stopped"}`(`stop_requested`=true, 수집된 후보 보존) | 로그인 | 404 · 409 이미 종료 |
| A-06 | GET | `/v1/candidates/{id}/evidence` | — | `candidate{id, title, status}`, `prev{observed_at, view_count}`(없으면 null), `curr{observed_at, view_count}`, `growth_pct`, `reason`(←`candidate_verdicts.reason`), `needs_prev`(이전 관측 없음), `next_observation_at`. 대표 판정 프로필 기준 | 로그인 | 404 후보 없음(타 워크스페이스 포함). 대표 판정 없음 → 200·prev/curr null·`needs_prev` true |
| A-07 | POST | `/v1/verify-runs` | `Idempotency-Key`, `profile_ids[]`(생략 시 선택된 프로필) | `job{id, kind:"verify", status}`, `checked`, `skipped_recent`(24시간 미만), `failed`, `counts{total, producible, pending, excluded, used}`(워커 불필요, 동기 응답) | 로그인 | 400 · 409 검증 진행 중 · 429 `QUOTA_EXCEEDED`(남은 후보는 이전 판정 유지) · 502 |
| A-08 | PATCH | `/v1/candidates/{id}/used` | `used`(bool) | `id`, `used`, `used_at`(Q4 수동 표시 제안). 제작 전환 지표 측정원(`01_PRD.md#5`) | 로그인 | 404 |

## 워커 API (수집 워커 → FastAPI, 아웃바운드 전용)
`Authorization: Bearer <워커 토큰>`(`workers.token_hash`로 검증, 사용자 JWT 아님). 로컬 포트 개방·DB 직접 접속 없음. 화면 ID 없음.
| ID | 메서드 | 경로 | 입력 | 출력 | 권한 | 오류 |
|---|---|---|---|---|---|---|
| W-01 | POST | `/worker/v1/jobs/claim` | — (폴링, 간격 가정 5~10초) | `job{id, kind:"collect", profiles[]{id, market, format, category, min_views, keywords, cc_only, include_broadcast}, resume_from_profile_id?, limit}` 또는 204(작업 없음) | 워커 토큰(자기 워크스페이스 큐만) | 401 토큰 무효·폐기 |
| W-02 | POST | `/worker/v1/heartbeat` | `job_id?`, `chrome[]{profile_id, state(`ready`·`resize_needed`·`login_needed`·`error`), detail}` | `stop_requested`(bool) (←`jobs.stop_requested`). `worker_heartbeats`·`job_profile_runs` 갱신 | 워커 토큰 | 401 · 404 job 없음 |
| W-03 | POST | `/worker/v1/jobs/{id}/candidates` | `profile_id`, `items[]{video_id, title, thumbnail_url, genre, category, format, market, channel_id, channel_title}`(형식 검증, 신뢰 안 함. 요청당 ≤200) | `accepted`, `duplicates`. 신규는 YouTube 1차 관측 후 근거 대기 판정 | 워커 토큰 | 400 형식 · 404 · 409 중지됨·종료됨 · 502 |
| W-04 | POST | `/worker/v1/jobs/{id}/finish` | `status`(`done`·`failed`), `error?`(쿠키·경로 금지) | `job{status}` | 워커 토큰 | 404 · 409 이미 종료 |

## 03 추적
| 화면 | API ID | 비고 |
|---|---|---|
| AUTH-01 | A-01 | |
| DASH-01 | A-02 | 요약 4칸 중 3칸은 미연동(`01_PRD.md#3` 이후): "—"+"운영 사이트 연동 전" 라벨(`03_SCREENS_UX.md` 상태표) |
| MON-01 | A-03, A-04, A-05, A-07, A-08 | 진행 표시는 A-05 GET 폴링(간격 가정 3초) |
| MON-D1 | A-03 | |
| MON-D2 | A-06 | |

## 보안 메모 (`01_PRD.md#8` 위협 메모 적용)
| 항목 | 내용 |
|---|---|
| 노출 면 | A-02~A-08은 로그인 사용자만. CSRF·로그인 제한 등 웹 면은 `01_PRD.md#8`. W-01~W-04는 워커 토큰만. 공개·웹훅·업로드 없음 |
| 인가 | 모든 쿼리에 `workspace_id` 조건 + RLS. 경로의 id가 타 워크스페이스면 403이 아닌 404(존재 노출 방지) |
| 남용 | 실행류 멱등 키 + 워크스페이스당 동시 1건, 실행당 후보 200, 429 처리. 조회(A-04)는 요청당 저장소 호출 약 8회·size≤60·page≤1000 — 내부 도구라 수용, 사용자·후보가 늘면 요청 속도 제한 추가 |
| 로그 | 실행·성공/실패 기록. 키·JWT·워커 토큰·쿠키 기록 금지 |
