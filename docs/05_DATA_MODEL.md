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
| api_quota_daily | YouTube API 일 사용량(서버 전체 1개 카운터) | day(date PK, America/Los_Angeles 기준), units(int) | **일반 사용자 접근 없음**(정책 없음). API만(`reserve_quota` RPC로 원자적 예약) | 상한 8,000 unit(`adr/0002`). 워크스페이스 열 없음(키가 서버 전체 1개) — 공통 규칙의 예외 |

## 제작 테이블 (카테고리형, 흐름 `02b_PRODUCTION_FLOW.md`)
| 테이블 | 목적 | 주요 컬럼 | RLS 기준 | 비고 |
|---|---|---|---|---|
| production_jobs | 제작 작업 1건(원본·구간·상태) | id, workspace_id, title, status(`draft`·`preparing`·`review`·`rendering`·`inspect`·`done`·`failed`), failed_stage(`prepare`·`audio`·`render`·null), error_code(null, 워커 보고 코드 + 서버 생성 `worker_offline`), candidate_id(→candidates, null 허용), source_kind(`upload`·`url`(P1)), source_url(null, http/https만, P1), rights_confirmed(bool), rights_confirmed_by·rights_confirmed_at, license_cc(bool·null=미확인), credit(text·null, 업로더·저작자), source_start_sec(numeric ≥0, 원본 전체 기준), segment_len_sec(numeric 0 초과 ≤180, 배포본 규격), lang(`ko`, P2 전까지 단일), preset_version(text), source_meta(jsonb: duration_sec·width·height·has_audio, prepare 완료 때 워커 보고), current_revision_id(→edit_revisions), ai_draft_count(int, 상한은 `01_PRD.md#7` Q7), retry_count(prepare 재시도, 상한 `02_ARCHITECTURE.md#3-3`), claimed_by(→workers, prepare 수령), updated_at(진행 보고 시각, 오프라인 평가 기준), requested_by, created_at, completed_at | 읽기: 구성원. 쓰기: API만(워커는 API 경유) | check: `source_kind`=`url`이면 `source_url` not null·`rights_confirmed`=true. 상태 전이 `02b_PRODUCTION_FLOW.md#2`. index(workspace_id, status, created_at desc)·(candidate_id). 한 후보로 작업 여러 건 허용(재제작) |
| production_assets | 작업의 파일 메타(내용은 Storage) | id, workspace_id, job_id, kind(`source_upload`·`source`·`analysis`·`sheet`·`hook_audio`·`output_mp4`·`report`), storage_path, mime, size_bytes(bigint), duration_sec(numeric·null, 영상·음성 길이), status(`pending`·`ready`), render_run_id(null, `output_mp4`·`report`·워커 생성 `hook_audio`만), created_by(user 또는 worker), created_at | 읽기: 구성원. 쓰기: API만. 서명 URL은 API가 소유 확인 후 발급 | `storage_path`는 서버가 생성(아래 Storage). unique(storage_path). index(job_id, kind). `sheet`는 여러 건. 다운로드는 `ready`만. 확장자·mime 허용 목록(영상 mp4·mov·webm·mkv, 음성 wav·mp3·m4a — 가정)이며 ffprobe 확인은 워커 보고로 `ready` 전환 |
| edit_revisions | 편집안 리비전(승인 고정 단위) | id, workspace_id, job_id, rev_no(int, 1부터), schema_version(int), spec(jsonb, 아래 필드 표), origin(`user`·`ai_draft`(P1)), validation(jsonb: errors[]·warnings[] — `{code, path, message}`), approved_at(null), approved_by(null), created_by, created_at, updated_at | 읽기: 구성원. 쓰기: API만 | unique(job_id, rev_no). 승인된 행(`approved_at` not null)은 spec 수정 거부(API가 새 rev_no 생성). 승인은 `validation.errors`가 비었을 때만. 저장은 오류가 있어도 허용(경고·오류는 validation에 기록). 같은 작업에서 낮은 rev 승인본은 이력으로 보존 |
| render_runs | 렌더 실행 1회(멱등·재시도 단위) | id, workspace_id, job_id, revision_id, lang(`ko`), attempt(int, 1부터), retry_of(→render_runs, null), idempotency_key, preset_version, status(`queued`·`running`·`done`·`failed`), progress_pct(0~100), progress_stage(text), error_stage(`audio`·`render`·null), error_code(null, 워커 보고 코드 + 서버 생성 `worker_offline`), claimed_by(→workers), mp4_asset_id·report_asset_id·hook_audio_asset_id(→production_assets, null), requested_by, created_at, started_at, finished_at, updated_at(진행 보고 시각) | 읽기: 구성원. 쓰기: API만 | unique(workspace_id, idempotency_key). **부분 unique(job_id, revision_id, lang) where status in (`queued`,`running`,`done`)** = 같은 (작업, 리비전, 언어)는 하나만 진행·완료. 실패 run은 제외되므로 재시도는 새 행(attempt+1, 새 자산). 완료 run의 자산은 수정·덮어쓰기 없음. **부분 unique(workspace_id) where status in (`queued`,`running`)** = 워크스페이스당 렌더 1건(동시 렌더 없음, `01_PRD.md#3` 이후), A-15 409와 같은 규칙 |

### 편집안 `edit_revisions.spec` 필드 (project.json 매핑)
project.json 열은 배포본 규격 사본 `research/category-shorts-ref/project-format.md`와 대조 완료. 모든 시각은 초, **편집 0초(선택 구간 시작, 배포본 `source.mp4` 기준) 기준**. 원본 전체 기준 시작은 `source_start_sec`로 따로 둔다.
| spec 필드 | 타입·제약 | project.json | 서버 검증(Pydantic, 정본) |
|---|---|---|---|
| `lang` | `ko`(배포본은 `ko`·`ja`, `ja`는 P2) | `lang` | 작업 `lang`과 같아야 함 |
| `header.lines[2]` | 문자열 정확히 2개, 줄바꿈 없음 | `header` | 2개 아니거나 줄바꿈·빈 줄 → 오류. 글자 수 상한은 두지 않음: 폭을 넘으면 렌더러가 자동 축소, 축소해도 폭 초과면 렌더 실패(`text_too_long`, 아래 items와 같은 처리) |
| `hook.text` | 문자열(첫 자막과 뜻이 같아야 함) | `hook` | 빈 값 불가. 배포본은 `hook` 또는 `hook_audio` 중 하나면 통과 — **`hook.text` 필수는 배포본보다 강화한 Nomadroom 규칙(의도)** |
| `hook.audio_asset_id` / `hook.tts{voice, rate?}` | 둘 중 하나. P0=첨부 `hook_audio` 자산 ID(이 작업 소유), (P1)=TTS(`voice`=edge-tts 음성 이름, `rate` 기본 `+50%`) | `hook_audio`(경로) / `voice` · `rate` | 둘 다·둘 다 없음 → 오류. 첨부는 TTS를 건너뛰고 무음 정리만. `훅 길이 + 0.08초` > 첫 자막 종료는 **렌더 워커가 실측**해 판정(정본 `04_API.md` W-09). 승인 때 길이는 null 허용(브라우저 audio 메타 길이는 참고 표시만) |
| `duration` | number 0.1 이상, ≤ `source_meta.duration_sec`(analysis 길이)+0.05, ≤180 | `duration` | 구도·자막 끝이 이 값을 넘으면 범위 초과 오류. NaN·무한 불가. 실제 출력 길이는 렌더러가 1/30초 단위로 올림 |
| `shots[]{start,end,scale,y}` | number 4개 | `shots` `[시작, 끝, 배율, Y]` | 0초에서 `duration`까지 공백·겹침 없이 이어짐. 배율 1~3, `Y≤280`, `Y+1080×배율≥1080`(위반 = 빈 화면, 오류). 좌표는 608×1080 비율 맞춤·중앙 크롭 이후 기준 |
| `items[]{start,end,kind,text,y?}` | 최소 1개. kind: `white`(흰색)·`paren`(노란 괄호)·`emph`(초록 박스). `text` 공백뿐 불가. `y?`=자막 중심 Y, 310~1030 | `items` `[시작, 끝, 종류, 문구(, Y)]` | 시간순·겹침·범위 초과 오류. 별표·괄호는 자동 삽입 안 함(문구에 직접). **첫 자막 start=0 아니면 오류**. 서버는 문구 공백만 검사. 너무 긴 문구는 렌더러가 폭 초과로 판정(`text_too_long`: 렌더 실패 → 편집안 검토 복귀, `hook_too_long`과 같은 처리). 표시 1.4초 미만 → 경고(렌더 안 막음, 배포본에 없는 Nomadroom 추가) |
| (P1) `overlays[]{kind,text,start,end,x,y,ref?}` | kind: `comment`·`source`. 화면 위치 x·y | (없음 — 배포본 밖 확장, 어댑터가 별도 렌더 단계로 변환) | 범위 초과 오류, 자막과 시간·위치 겹침 → 경고(검수 화면 확인) |
| `source_start_sec` · `preset_version` | 작업 값의 복사본(읽기 전용) | (어댑터가 변환에서 제외) | 작업 값과 다르면 거부. 값은 리비전이 렌더된 입력을 재현하기 위해 기록 |
| (어댑터가 채움) | — | `source`=`source.mp4`, `output`=`result_ko.mp4` | spec에 두지 않음(경로 필드 금지) |
- 오류 코드는 `field_path`와 함께 반환(예: `shots.gap`·`items.overlap`·`items.first_not_zero`. 훅 길이는 서버 검사 대상 아님). 경로 안전: spec 어디에도 파일 경로·URL 문자열 필드를 두지 않는다(자산은 ID만, 절대 경로·`..`는 400 `VALIDATION`).
- 편집안 승인 후 입력(spec) 변경 = 새 리비전. 렌더 어댑터가 승인 리비전을 `project.json`으로 변환해 워커 작업 폴더에 둔다.

### Storage {#storage}
| 항목 | 규칙 |
|---|---|
| 버킷 | `production` 1개, **비공개**. `storage.objects` 정책은 `authenticated`·`anon` 모두 정책 없음(= 거부). 접근은 API가 발급한 서명 URL만 |
| 경로 | `{workspace_id}/{job_id}/{asset_id}.{ext}` — 값은 모두 서버가 생성한 uuid·허용 목록 확장자. 파일명·경로를 클라이언트·워커가 정하지 않음. 렌더 산출물도 새 `asset_id`라 재시도가 기존 파일을 덮어쓰지 않음 |
| 서명 URL | 용도 한정(업로드 PUT / 다운로드 GET), 단일 객체. 만료 값 정본 `04_API.md#제작-api`. 재발급은 소유 확인 후 |
| 보관·삭제 | 완료 후 30일, 원본은 렌더 완료 7일 후 삭제(제안, `01_PRD.md#7` Q5 미결). 삭제 작업은 API만, 자산 행은 `status`=`deleted`는 두지 않고 행째 삭제 |
