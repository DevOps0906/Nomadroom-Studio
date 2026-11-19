# task-035 예능형 API 연결

| 항목 | 내용 |
|---|---|
| 웨이브 | W6 |
| 선행 | task-034 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(A-09 입력 확장) · 워커 계약(W-05 task.format) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-09`·`#A-12`·W-05, `docs/02b_PRODUCTION_FLOW.md`, `docs/05_DATA_MODEL.md#예능형-spec` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/adapter*.py`, `apps/api/app/routes/worker_production.py`(W-05 task.format만), `apps/api/tests/production/**` |

## 할 것
- A-09 `format=variety` 허용(형식 고정, 이후 변경 불가)·preset_version 형식별. A-10 훅 음성 업로드는 variety에서 400. A-09 목록에 `format` 필터·`items[].format` 추가.
- A-12 저장·A-13 승인 검증을 format으로 분기. 렌더 어댑터가 승인 리비전을 `variety_project.json`으로 변환, W-05 `task.format`에 format을 싣는다(W-06은 inputs만).

## 하지 않을 것
- 렌더러(036), 화면(037), 받아쓰기·AI 초안(P1), 카테고리형 응답 형태 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production` 통과(variety 생성·저장·승인·어댑터 산출 JSON 스냅샷, 형식 변경 PATCH 거부, variety 훅 업로드 400)
- [ ] `cd apps/api && pytest -q` 전체 회귀 · 경로 필드 거부 테스트 유지

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- V1 어댑터 위치: 카테고리형과 같이 워커(`apps/worker/production/adapter_variety.py`)에 두고 task-036이 만든다. W-05 task.spec은 DB 원본 spec 그대로(계약 변경 없음). 035는 API 검증 분기만.
- V2 렌더러 전 차단: task-036 전까지 A-15에서 format=variety면 409(재시도 상한 낭비 방지). task-036에서 해제.
- V3 같은 Idempotency-Key로 format만 다른 POST는 D1(A-07 규칙)대로 기존 작업 200 유지.
- 쓰기 허용(최종): `apps/api/app/routes/production_jobs.py`(_validate·select·variety 개방) · `apps/api/app/routes/worker_production.py`(W-09 prepare 첫 리비전 validate_for_format만) · `apps/api/app/routes/production_render.py`(A-15 variety 409만) · `apps/api/app/production/validation_variety.py`(개수·길이·제어문자 상한만) · `apps/api/tests/production/**`(acceptance 제외) · `docs/04_API.md`(A-09·A-12·A-13·A-15).
- V4 저장·승인 검증: `validate_for_format(job.format, …)`, source_size=job.source_meta(width,height)(없으면 source_size.missing 오류), segment_len=min(segment_len_sec, source duration). source_start_sec·preset_version 비교는 두 형식 모두 유지.
- V5 이미 구현된 것(W-05 format·목록 필터·variety 훅 업로드 400·A-14 409)은 회귀 테스트만. 기존 "variety 400 준비 중" 테스트는 shopping만 400으로 고친다.
- V6 variety 입력 상한: subtitles·reactions 각 200개, header 줄·자막 문구 길이 상한, 제어문자(\u0000 등) 거부 — 테스트 고정. 형식 변경 PATCH는 실제 응답 코드를 04와 맞춰 단정.

## 구현 결정 (2026-11-19, builder)
- A-09: `PRESET_VERSION`에 `variety`=`variety-1080-v1`. `PRESET_VERSION`에 없는 format(shopping)만 400 "준비 중". 같은 키·다른 format은 D1대로 기존 작업 200(V3 테스트).
- A-12·A-13: `_validate`가 `validate_for_format(job.format, …)`을 부른다. variety는 segment_len=min(`segment_len_sec`, 최신 ready source 길이), source_size=`source_meta`(width·height). 크기가 없으면 스키마 오류가 없을 때만 `source_size.missing`(path `source_size`)을 추가(저장은 되고 승인은 400). `_validate`는 `production_ai.py`도 쓰지만 job.get으로 읽어 category 경로는 그대로다.
- W-09 prepare 첫 리비전: `validate_for_format(job.format, {}, source_size=meta 폭·높이)`. 빈 spec은 스키마 오류에서 멈추므로 segment_len은 넘기지 않는다(job select 변경 없음).
- A-15: RPC 전에 job(`id,format`, workspace 조건)을 읽고 없으면 404, `format`≠`category`면 409 `CONFLICT`(field `format`). 렌더 run·RPC 호출 없음. A-16 재시도는 variety run이 생길 수 없어 그대로 둠.
- V6 상한(가정, `validation_variety.py` 상단 상수): subtitles·reactions 각 200(`schema.too_long`), header 줄 60자·자막/반응 문구 200자(`schema.string_too_long`), 제어문자 `[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]` 거부(`schema.value_error`). LF·CR은 제외해 header 줄바꿈은 기존대로 `header.invalid`(의미 오류). 모두 스키마 오류라 400·저장 안 함.
- 형식 변경 PATCH: `JobPatchIn` extra=forbid → 400 `VALIDATION` field `format`(04 A-09에 명시).
- 테스트: `test_jobs_api.py`(test_v*), `test_render_runs.py`(V2), `test_worker_production.py`(V4 첫 리비전). 기존 "variety 400" 테스트는 shopping 400으로 교체.

## 리뷰 반영 결정 (2026-11-19, code·security 🔴 없음)
- R1 `_CONTROL` 확장: C0(LF·CR 제외)·DEL·C1(`\x80-\x9f`)·제로폭/방향 표시(U+200B-200F)·줄/문단 구분(U+2028·2029)·방향 제어(U+202A-202E, U+2066-2069)·BOM(U+FEFF) 거부(`schema.value_error`). header 줄바꿈 판정(`header.invalid`)에도 U+2028·2029 포함(스키마에서 먼저 막히므로 방어용).
- R2 A-16 재시도도 A-15와 같은 `_require_category`로 variety면 409(field `format`), 없는 작업 404. RPC 호출 없음.
- R3 `cuts`에 스키마 상한 `max_length=60`(파싱 단계 `schema.too_long`, 400·저장 안 함). 의미 오류 `cuts.count`는 0개일 때만 남는다. task-034 테스트의 61개 단정을 `schema.too_long`으로 바꿈.
- R4 `production_ai.py` A-14 job 조회에 `segment_len_sec`·`source_meta` 추가(format은 이미 있음). 동작 변화 없음(task-040 대비), 회귀 테스트만.
