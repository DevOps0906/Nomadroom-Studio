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
| production_jobs | 제작 작업 1건(원본·구간·상태) | id, workspace_id, title, format(`category`·`variety`, 기본 `category`, 생성 후 변경 불가, `variety`는 task-035부터 허용), status(`draft`·`preparing`·`review`·`rendering`·`inspect`·`done`·`failed`), failed_stage(`prepare`·`audio`·`render`·null), error_code(null, 워커 보고 코드 + 서버 생성 `worker_offline`), transcribe_state(null·`queued`·`running`·`done`·`failed`, P1 예능형 받아쓰기 상태 — job `status`와 분리), transcribe_error(null·코드: `transcribe_failed`·`worker_offline`, `error_stage`에는 넣지 않음), candidate_id(→candidates, null 허용), source_kind(`upload`·`url`(P1)), source_url(null, http/https만, P1), rights_confirmed(bool), rights_confirmed_by·rights_confirmed_at, license_cc(bool·null=미확인), credit(text·null, 업로더·저작자), source_start_sec(numeric ≥0, 원본 전체 기준), segment_len_sec(numeric 0 초과 ≤180, 배포본 규격), lang(`ko`, P2 전까지 단일), preset_version(text, 형식별: category 현행값·variety 예 `variety-1080-v1`), source_meta(jsonb: duration_sec·width·height·has_audio, prepare 완료 때 워커 보고), current_revision_id(→edit_revisions), ai_draft_count(int, 상한은 `01_PRD.md#7` Q7), retry_count(prepare 재시도, 상한 `02_ARCHITECTURE.md#3-3`), claimed_by(→workers, prepare 수령), updated_at(진행 보고 시각, 오프라인 평가 기준), requested_by, created_at, completed_at | 읽기: 구성원. 쓰기: API만(워커는 API 경유) | check: `format` in (`category`,`variety`). `transcribe_state` in (null,`queued`,`running`,`done`,`failed`). `source_kind`=`url`이면 `source_url` not null·`rights_confirmed`=true. 상태 전이 `02b_PRODUCTION_FLOW.md#2`. index(workspace_id, status, created_at desc)·(candidate_id). 한 후보로 작업 여러 건 허용(재제작) |
| production_assets | 작업의 파일 메타(내용은 Storage) | id, workspace_id, job_id, kind(`source_upload`·`source`·`analysis`·`sheet`·`hook_audio`·`narration`(첨부 녹음, 쇼핑·ja 리비전의 `voice.narration_asset_id` 전용)·`output_mp4`·`report`·`transcript`(P1, 예능형 받아쓰기 JSON, 원본 시각 기준 segment 목록)), storage_path, mime, size_bytes(bigint), duration_sec(numeric·null, 영상·음성 길이), status(`pending`·`ready`), render_run_id(null, `output_mp4`·`report`·워커 생성 `hook_audio`만), created_by(user 또는 worker), created_at | 읽기: 구성원. 쓰기: API만. 서명 URL은 API가 소유 확인 후 발급 | `storage_path`는 서버가 생성(아래 Storage). unique(storage_path). index(job_id, kind). `sheet`는 여러 건. 다운로드는 `ready`만. 확장자·mime 허용 목록(영상 mp4·mov·webm·mkv, 음성 wav·mp3·m4a — 가정, 워커 생성 `analysis`·`report`·`transcript`는 json)이며 ffprobe 확인은 워커 보고로 `ready` 전환 |
| edit_revisions | 편집안 리비전(승인 고정 단위) | id, workspace_id, job_id, rev_no(int, 1부터), schema_version(int), spec(jsonb, 아래 필드 표), origin(`user`·`ai_draft`(P1)), validation(jsonb: errors[]·warnings[] — `{code, path, message}`), approved_at(null), approved_by(null), created_by, created_at, updated_at | 읽기: 구성원. 쓰기: API만 | unique(job_id, lang, rev_no)(`lang`·`derived_from`·`kind` 확장은 `#쇼핑-확장`). 승인된 행(`approved_at` not null)은 spec 수정 거부(API가 새 rev_no 생성). 승인은 `validation.errors`가 비었을 때만. 저장은 오류가 있어도 허용(경고·오류는 validation에 기록). 같은 작업에서 낮은 rev 승인본은 이력으로 보존 |
| render_runs | 렌더 실행 1회(멱등·재시도 단위) | id, workspace_id, job_id, revision_id, lang(`ko`·`ja`, `#쇼핑-확장`), attempt(int, 1부터), retry_of(→render_runs, null), idempotency_key, preset_version, status(`queued`·`running`·`done`·`failed`), progress_pct(0~100), progress_stage(text), error_stage(`audio`·`render`·null), error_code(null, 워커 보고 코드 + 서버 생성 `worker_offline`), claimed_by(→workers), mp4_asset_id·report_asset_id·hook_audio_asset_id(→production_assets, null), requested_by, created_at, started_at, finished_at, updated_at(진행 보고 시각) | 읽기: 구성원. 쓰기: API만 | unique(workspace_id, idempotency_key). **부분 unique(job_id, revision_id, lang) where status in (`queued`,`running`,`done`)** = 같은 (작업, 리비전, 언어)는 하나만 진행·완료. 실패 run은 제외되므로 재시도는 새 행(attempt+1, 새 자산). 완료 run의 자산은 수정·덮어쓰기 없음. **부분 unique(workspace_id) where status in (`queued`,`running`)** = 워크스페이스당 렌더 1건(동시 렌더 없음, `01_PRD.md#3` 이후), A-15 409와 같은 규칙 |

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
| (P1) `overlays[]{kind,text,start,end,x,y,ref?}` | kind: `comment`·`source`. 화면 위치 x·y | (없음 — 배포본 밖 확장, 어댑터가 별도 렌더 단계로 변환) | 범위 초과 오류, 자막과 시간·위치 겹침 → 경고(검수 화면 확인). x·y=카드 중심 px(608×1080 화면, 밖이면 `overlays.pos`). 문구는 한 줄·폭 단위 80 이하(공백·ASCII 구두점 1, 그 밖 2 = 전각 40자, 위반 `overlays.text.long`). 최대 20개(`overlays.count`). 같은 종류 구간 겹침은 오류(`overlays.overlap`). 자막 겹침 경고(`overlays.caption_overlap`)는 시간이 겹치고 \|오버레이 y − 자막 y\| < 75일 때(자막 기본 y: emph 390, 그 외 700) |
| `source_start_sec` · `preset_version` | 작업 값의 복사본(읽기 전용) | (어댑터가 변환에서 제외) | 작업 값과 다르면 거부. 값은 리비전이 렌더된 입력을 재현하기 위해 기록 |
| (어댑터가 채움) | — | `source`=`source.mp4`, `output`=`result_ko.mp4` | spec에 두지 않음(경로 필드 금지) |
- 오류 코드는 `field_path`와 함께 반환(예: `shots.gap`·`items.overlap`·`items.first_not_zero`. 훅 길이는 서버 검사 대상 아님). 경로 안전: spec 어디에도 파일 경로·URL 문자열 필드를 두지 않는다(자산은 ID만, 절대 경로·`..`는 400 `VALIDATION`).
- 편집안 승인 후 입력(spec) 변경 = 새 리비전. 렌더 어댑터가 승인 리비전을 `project.json`으로 변환해 워커 작업 폴더에 둔다.

### 예능형 `edit_revisions.spec` 필드 (`format`=`variety`) {#예능형-spec-필드}
출력 1080×1920·30fps. 흰 캔버스, 영상 띠 y 560~1376(816px), 제목 약 328~496. 수치는 완성본 실측(`research/variety-shorts-zip-analysis.md#3`)이며 렌더러 상수 + `preset_version`으로 고정. 시각은 초. 카테고리형 표와 별개이고 그쪽 규칙은 바꾸지 않는다. 서버 검증은 `format`으로 분기(Pydantic, 정본).
| spec 필드 | 타입·제약 | 서버 검증 (오류 `E` · 경고 `W`) |
|---|---|---|
| `lang` · `source_start_sec` · `preset_version` | 카테고리형과 같은 읽기 전용 복사본 | 작업 값과 다르면 거부 |
| `header.lines` | 문자열 1~2개(가정, Q11) | E `header.invalid`(0개·3개 이상·줄바꿈·빈 줄). 폭 초과는 자동 축소, 그래도 넘으면 렌더 실패 `text_too_long` |
| `cuts[]{src_start,src_end,scale,x,y}` | 1~60개, 배열 순서가 출력 순서(출력 시각 = 컷 길이 누적). 원본 시각은 선택 구간 0초 기준. scale 1~3(가정, Q11). **좌표 기준**: 원본을 캔버스 폭 1080에 맞춘 상태가 배율 1(원본 높이 = 1080×원본H/원본W×배율). x·y = 띠 중심(540, 968)에서 원본 중심까지의 px 이동(CapCut 정규화 x는 px = x×540으로 환산) | E `cuts.count`(0개·60 초과, 가정 Q11) · E `cuts.out_of_range`(`0 ≤ src_start < src_end ≤ segment_len` 위반) · E `cuts.too_short`(길이 0.2 미만, 가정 Q11) · W `cuts.short`(0.5 미만, 가정 Q11) · E `cuts.empty_area`(띠 사각형 0~1080 × 560~1376이 이동·확대된 원본 사각형 안에 다 들어가지 않음) · E `cuts.total_too_long`(출력 총길이 180 초과, 가정). 원본 구간 겹침·반복은 허용 |
| `subtitles[]{start,end,style,text}` | 출력 시각 기준. style `line`(검정 알약)·`punch`(빨강 알약). 한 번에 1개 | E `subtitles.overlap` · E `subtitles.out_of_range`(총길이 초과·start≥end) · E `subtitles.empty_text`(공백뿐) · E `subtitles.style`(허용 외) · W `subtitles.short`(1.4 미만). 공백 허용, 첫 자막 0초 불필요 |
| `reactions[]{start,end,text,x,y}` | 빨강+흰 테두리, 위치 자유(캔버스 안). 대사 자막과 겹쳐도 됨 | E `reactions.out_of_range`(시간·좌표 범위 초과) · E `reactions.empty_text` · W `reactions.overlap`(반응끼리 시간 겹침) |
| 음성 | spec에 필드 없음. 각 컷의 원본 소리 그대로 + 전체 음량 정규화(훅 음성 없음, `hook_too_long` 없음) | 컷별 속도·J/L 컷·색 효과·BGM은 미지원(후속) |
- 경로·URL 문자열 필드 금지(자산은 ID만, 위반 400 `VALIDATION`)는 카테고리형과 같다. 렌더 어댑터가 승인 리비전을 `variety_project.json`(Nomadroom 자체 형식, CapCut 읽기·쓰기 없음)으로 변환한다. 코드는 서버 검증 코드이고 렌더 실패 코드는 `04_API.md` W-09.
- 리포트(`report`): 해상도·길이·오디오 유무·컷 수·컷별(출력 시작·원본 시작·길이)·사용 글꼴과 대체 여부.
- 글꼴(Cafe24 Ohsquare·잘난체)은 라이선스 확인 전(`01_PRD.md#7` Q9, 미확인). 실패 시 Pretendard Black(OFL)로 대체하고 리포트에 기록.
- 렌더 프리셋 `variety-1080-v1` 상수(task-036, 워커 `production/variety/text.py`·`adapter_variety.py`, 분석 #3 실측 + 가정): 제목 Pretendard-Black 76px(자동 축소 최소 24) 빨강 `#E8202A`+흰 테두리 6px, 2줄 중심 y 370·454(1줄 412) · 대사 자막 알약 중심 y 1240, `line` 52px 흰 글자+검정(알파 230) · `punch` 60px 흰 글자+빨강, 안쪽 여백 28×16 · 반응 자막 48px 빨강+흰 테두리 5px, 중심 (x, y)를 캔버스 안으로 당김 · 문구 최대 폭 1000px(넘으면 `text_too_long`) · 컷 경계 = 누적 출력 시각×30 반올림 프레임, 소리도 같은 경계(1프레임 = 1600샘플@48kHz) · 음량 loudnorm I=-14 · H.264 CRF 18(medium)/AAC 192k.

### 쇼핑·일본어판 확장 (흐름 `02b_PRODUCTION_FLOW.md#유형-분기`) {#쇼핑-확장}
위 제작 테이블 행의 의미는 바꾸지 않고 컬럼·규칙만 더한다. 수치는 모두 가정.
| 대상 | 추가·변경 | 규칙 |
|---|---|---|
| production_jobs | `kind`(`general`(기본)·`shopping`, 생성 후 변경 불가) | `format` check에 `shopping` 추가. `kind`=`shopping` ⇔ `format`=`shopping`, `kind`=`general`이면 `format` in (`category`,`variety`) |
| production_jobs | `vertical`(null·`product`·`travel`) | `kind`=`shopping`이면 필수, 아니면 null |
| production_jobs | `brief`(jsonb, 쇼핑만) | 상품: 제품명·불편 1개·실제 장면 3~5·빼야 할 말·확인된 사실. 여행: 목적지·상품 종류(숙소·투어·패키지)·소구점 1개·장면 3~5·확인된 사실. `target`(성별·연령대, 메모용) 포함 |
| production_jobs | `affiliates`(jsonb[], `{lang, partner, url}`) | 운영자가 발급한 링크를 수동 입력. 배열, 원소 lang `ko`·`ja`·partner 비어 있지 않음·url은 https만(DB check), 클라이언트 번들·로그에 키 없음. 링크는 spec·산출물 파일에 박지 않고 게시 문구에만 쓴다 |
| production_jobs | `comment_keyword`(text·null) | 댓글 유도 단어(게시 문구에 사용) |
| production_jobs | `current_ja_revision_id`(→edit_revisions, null) | 일본어판 현재 리비전. `current_revision_id`는 ko 그대로. (id, job_id) 복합 FK로 같은 작업만 |
| production_jobs | `candidate_id` FK를 (candidate_id, workspace_id)→candidates(id, workspace_id)로 교체 | 다른 워크스페이스 후보 참조 거부, 후보 삭제 시 `candidate_id`만 null |
| production_jobs | `lang` | 원본 작업 언어 `ko` 고정. 일본어판은 작업이 아니라 리비전·렌더의 `lang`이다 |
| production_assets | `kind`에 `source_upload`·`source`가 작업당 여러 건(쇼핑), `bgm`·`image` 추가 | `rights`(jsonb·null): `{basis(`own`·`licensed`·`permission`·`quote`·`platform_audio`·`ai_generated`(P1)), source_url, author, has_person, portrait_consent, note, gen?}`. `gen`={platform, model, request_id, cost_krw(정수 원)}는 basis=`ai_generated`일 때만 필수(`generation_runs`와 같은 값 복사). `ai_generated` 자산(`source_upload`)은 입력 사진의 권리를 이어받고 `reviewed`(bool)=true여야 승인. 쇼핑은 모든 원본·이미지·BGM이 basis 필수, `has_person`=true면 `portrait_consent`=true여야 승인. 일반쇼츠는 선택(기존 `rights_confirmed` 유지) |
| edit_revisions | `lang`(`ko`(기본)·`ja`), `derived_from`(→edit_revisions, null) | `ja`는 `derived_from` 필수·승인된 ko 리비전. **unique(job_id, lang, rev_no)**(기존 unique(job_id, rev_no)를 대체, ko 행의 의미는 같음). `rev_no`는 언어별로 1부터. 승인·spec 불변 규칙은 언어별 동일 |
| render_runs | `lang`(`ko`·`ja`) | `render_runs.lang`은 렌더하는 리비전의 `lang`과 같아야 함. 부분 unique(job_id, revision_id, lang)는 그대로 |
| generation_runs (신규, P1 task-054) | AI 영상 생성 요청 1회 | id, workspace_id, job_id, source_asset_id(→입력 `image`), result_asset_id(→`source_upload`, null), cut_ref(spec 컷 순번 메모), platform, model, duration_sec(초), est_cost_krw·actual_cost_krw(정수 원, null=미정), status(`quoted`·`confirmed`·`running`·`done`·`failed`), request_id(플랫폼 요청 ID, null), idempotency_key, requested_by, created_at, finished_at | 읽기: 구성원. 쓰기: API만(워커·웹 직접 없음). 키는 FastAPI만 | unique(workspace_id, idempotency_key). 월 합계(`confirmed` 이후 est/actual) + 요청 est > `workspaces.gen_monthly_budget_krw` 또는 작업 합계 > `gen_job_cap_krw`이면 거부(409). 환율 기준·재생성 과금은 Q16 |
| workspaces (예산, 가정) | 월 예산·작업당 상한 | `gen_monthly_budget_krw`·`gen_job_cap_krw`(정수 원, null=AI 생성 사용 불가) | 변경은 마이그레이션·시드만(설정 화면 없음, `01_PRD.md#6`) | 금액·위치 모두 `01_PRD.md#7` Q16 결정 전 가정 |
| 일본어판 렌더 | 글꼴 Noto Sans CJK JP Bold(OFL), 제휴·표기는 ja 값(라쿠텐·아마존, "PR") | 리포트에 사용 글꼴 기록. 예능형 원본 소리 duck 15%·TTS rate 상한 +30% |

### 쇼핑 `edit_revisions.spec` 필드 (`format`=`shopping`) {#쇼핑-spec-필드}
출력 1080×1920·30fps, 15~20초 기준(가정). 카테고리형·예능형 표와 별개이며 서버 검증은 `format`으로 분기(Pydantic, 정본). 경로·URL 문자열 필드 금지(자산은 ID만). 오류 `E`·경고 `W`.
| spec 필드 | 타입·제약 | 서버 검증 |
|---|---|---|
| `lang` · `source_start_sec` · `preset_version` | 읽기 전용 복사본 | 작업·리비전 값과 다르면 거부 |
| `script[4]{text}` | 정확히 4문장, 공백 포함 합계 110~140자(가정) | E `script.count`(4문장 아님) · E `script.unverified`(`[확인 필요]` 잔존) · W `script.length`(합계 범위 밖) · W `script.banned_phrase`("강력 추천"·"인생템"·"지금 바로" 등, 목록은 금지어 설정) · W `script.product_in_first`(1번 문장에 제품명) |
| `cuts[]{source_asset_id, src_start, src_end, scale, x, y, sentence(1~4), masks[]{x,y,w,h}, motion?{type}}` | 원본 여러 개 사용, 컷은 문장 번호에 묶임. `masks`=원본 외국어 자막 가림 블러 영역. `source_asset_id`는 영상(`source`·`source_upload`) 또는 `image`. `image` 컷은 `motion.type`(`pan`·`zoom`·`none`, 기본 `zoom`, 가정)을 렌더러가 적용하고 `src_start`·`src_end`는 표시 길이(초). 영상 컷에는 `motion` 없음 | **시각 기준(task-045 팀장 결정)**: 쇼핑 prepare는 job 구간(`source_start_sec`·`segment_len_sec`)을 쓰지 않고 원본마다 0초부터 전체(최대 60초, 넘으면 앞 60초)를 파생 `source`로 만든다. 영상 컷 `src_start`·`src_end`는 파생 source 시각 = 원본 0초 기준이다. 컷 자산은 서로 다른 것 20개 이하(원본 10 + 사진 10), 문장 음성 1개 ≤60초·합계 ≤180초(워커 render_failed) · E `cuts.sentence_empty`(문장에 컷 0개) · E `cuts.out_of_range`(원본 길이 밖) · E `cuts.source_invalid`(이 작업 소유 `source` 아님) · E `cuts.empty_area`(빈 화면, 예능형과 같은 규칙) · E `masks.out_of_range`(캔버스 밖) · E `cuts.motion_invalid`(`image`가 아닌데 `motion`, 또는 허용 외 type) · W `sources.few`(사용 원본 3개 미만) |
| `voice{tts{voice, rate} \| narration_asset_ids[4]}` | 둘 중 하나 필수. `narration_asset_ids`는 문장별 녹음 정확히 4개(문장 순서, 서로 다름, task-045 사용자 결정), 각각 이 작업 소유 `ready` `narration` kind. 문장 i 자막 구간 = 녹음 i 실측 길이. TTS면 문장마다 1회(4회, 하나라도 실패하면 `tts_failed`) | E `voice.missing` · E `voice.both` · E `voice.narration_count`(4개 아님·중복) · E `voice.asset_invalid`(`narration` kind가 아니거나 이 작업 소유·`ready` 아님) |
| `source_audio` · `bgm_asset_id?` | `mute`(기본)·`duck` | E `bgm.rights_missing`(BGM `rights.basis` 없음) |
| `cta.text` · `disclosure.text` | 4번 문장 화면 문구 / 표기는 고정 문구만(ko "제휴 링크 포함", ja "PR", task-045 팀장 결정). 위치 고정 | E `cta.empty` · E `disclosure.empty` · E `disclosure.fixed`(고정 문구와 다름) |
| (승인 조건, 자산) | 모든 원본·이미지·BGM `rights.basis` 입력, `has_person`이면 `portrait_consent` | E `rights.missing` · E `rights.portrait_consent` · E `rights.image_basis`(`image`의 basis가 `own`·`licensed`·`ai_generated`가 아님 — 제휴처·숙소 제공 사진 금지, task-045 팀장 결정) · E `gen.unreviewed`(`ai_generated` 컷 자산 `reviewed`≠true, 환각 검수) |
- 자막은 렌더러가 TTS 실측 길이에 맞춰 문장 → 구간으로 자동 배치(spec에 자막 필드 없음). 컷 길이 합계는 렌더러가 문장 길이에 맞춰 늘이거나 줄이고(마지막 컷 자르기·정지 프레임) 리포트에 기록.
- 금지 품목(의약품·건강기능식품)은 작업 생성(A-09)에서 막고, 과장·효능 표현은 `script.banned_phrase` 목록으로 검증. 일본어판 규칙은 아래 표.
- 일본어판(`lang`=`ja`) 검증: `derived_from` 필수, 컷·구도·마스크가 ko와 다르면 W `ja.cuts_changed`. ko 승인본이 더 새로우면 W `ja.stale`("원본 변경됨"). 예능형 TTS가 자막 구간을 넘으면 렌더 후 W `dub_overflow`(rate 상한 +30% 가정 후에도). 글자 수 범위(110~140)는 ja에 적용하지 않음(미확인, 일본어 기준 근거 필요).
- 리포트(`report`): 위 항목 + 원본·이미지·BGM의 출처·권리 목록, 컷 표, 사용 글꼴, 컷 길이 조정 기록.

### Storage {#storage}
| 항목 | 규칙 |
|---|---|
| 버킷 | `production` 1개, **비공개**. `storage.objects` 정책은 `authenticated`·`anon` 모두 정책 없음(= 거부). 접근은 API가 발급한 서명 URL만 |
| 경로 | `{workspace_id}/{job_id}/{asset_id}.{ext}` — 값은 모두 서버가 생성한 uuid·허용 목록 확장자. 파일명·경로를 클라이언트·워커가 정하지 않음. 렌더 산출물도 새 `asset_id`라 재시도가 기존 파일을 덮어쓰지 않음 |
| 서명 URL | 용도 한정(업로드 PUT / 다운로드 GET), 단일 객체. 만료 값 정본 `04_API.md#제작-api`. 재발급은 소유 확인 후 |
| 보관·삭제 | 완료 후 30일, 원본은 렌더 완료 7일 후 삭제(제안, `01_PRD.md#7` Q5 미결). 삭제 작업은 API만, 자산 행은 `status`=`deleted`는 두지 않고 행째 삭제 |
