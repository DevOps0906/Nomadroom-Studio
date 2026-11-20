# task-054 AI 영상 생성 연동

| 항목 | 내용 |
|---|---|
| 웨이브 | W9 |
| 선행 | task-047, Q16(플랫폼·예산·약관 확정) |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(AI 영상 API) · 새 키(서버 전용) · 비용 발생 · 사진 외부 전송 |
| 담당 | builder + tester |
| 근거 | `tasks/plan-shopping-japanese.md#여행 영상 생성과 비용`, `docs/research/shopping-shorts-notion-analysis.md#7`, `docs/04_API.md`·`docs/05_DATA_MODEL.md`(generation_runs) |
| 쓰기 허용 | `apps/api/app/production/videogen/**`, `apps/api/app/routes/production_jobs.py`(생성 요청), `supabase/migrations/`(새 번호, generation_runs), `apps/api/app/production/validation_shopping.py`(gen.unreviewed만), 해당 테스트, PROD-02S 컷별 "AI 생성"·검수 체크 |

## 할 것
- 착수 전: Q16(플랫폼 1개·월 예산·작업당 상한·상업 이용 약관) 확정, 유료 키 발급은 사용자 승인.
- 플랫폼 어댑터 인터페이스 + 품질 등급 2개(quality=힉스필드, economy=그록) 어댑터. 컷별 등급 선택·등급별 예상 비용. 입력 = 공식 사진 자산(권리 basis 확인됨) + 프롬프트, 결과 = `source_upload`(basis `ai_generated`, 플랫폼·모델·요청 ID·비용).
- 예상 비용 표시 → 확인 후 요청, 작업 상한·월 예산 초과 거부, 멱등 키, generation_runs 기록, 컷별 사람 검수 체크 3항목(물리 오류·불가능 앵글·실제 사진 대조, 전부 체크해야 승인).

## 하지 않을 것
- 키를 웹·워커에 두기, 예산 확인 없는 생성, 권리 미확인 사진 전송, 세 번째 플랫폼 추가(Q16 확정 전).

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_videogen.py` 통과(모의 플랫폼: 정상·실패·예산 초과 거부·멱등 재요청 무과금)
- [ ] `supabase test db` 통과(generation_runs RLS)

## 착수 결정 (팀장 2026-11-20, challenger REVISE 반영)
- G0 Q16 우선: 어댑터 인터페이스 + **xAI(그록) 어댑터 1개**와 비용 상한 장치만(힉스필드 없음). 기본 꺼짐: `VIDEOGEN_ENABLED`≠1 또는 키 없음 → 견적부터 503(계수·기록 없음). 실제 xAI 호출 없음(모의 어댑터로만 검증, 실제 호출·약관 확인은 사람 할 일).
- G1 생성 시점(🔴1): 견적·확인은 작업 상태 `draft`·`failed(prepare)`에서만(원본 업로드와 같은 단계). 결과는 `source_upload`로 저장되어 기존 prepare가 파생 `source`를 만든다(트리거 000023의 상태·10건 상한 그대로 적용). 상한·상태 때문에 저장이 거부되면 run=`failed`(`result_rejected`), 비용은 그대로 계상.
- G2 상태·이중 과금(🔴2): `quoted → confirmed(제출 전 계상) → running(request_id 있음) → done | failed | unknown`. submit 타임아웃·응답 불명 = `unknown`(est 계상, 자동 재제출 없음). 같은 run 재확인은 200 + 현재 run(재제출 없음), quoted가 아닌 다른 상태 확인은 해당 run 반환(04_API A-22의 "이미 확인됨 409" 문구를 이 규칙으로 정정). submit이 플랫폼의 명확한 4xx 거부로 끝난 경우만 `failed` + 비계상.
- G3 예산(🔴3·🟡4): workspaces `gen_monthly_budget_krw`·`gen_job_cap_krw` integer NOT NULL default 0 CHECK ≥0. `est_cost_krw` NOT NULL CHECK ≥1(USD×환율 **올림**), duration_sec 1~15 정수(가정). 계상 = confirmed·running·unknown·done·failed(제출 후) 전부, 금액 = coalesce(actual, est). 월 경계 KST. 확인 RPC가 job·workspace 행 잠금 뒤 다시 계산, unique(workspace_id, idempotency_key).
- G4 검수(🟡1): `production_assets.reviewed` boolean NOT NULL default false 별도 열 + `review_checks` jsonb, service_role RPC로만 갱신. `POST .../generation-runs/{run_id}/review {physics, angle, compare}` 셋 다 true여야 reviewed=true. `shopping.assets_map`이 이 열을 읽는다(기존 gen.unreviewed 검증 재사용). rights jsonb의 reviewed 키는 쓰지 않는다.
- G5 진행 확인(🟡2): GET 목록은 부작용 없음. `POST .../{run_id}/refresh`가 poll하고, 완료 처리는 running→finalizing 조건부 갱신(CAS)으로 1건만 수행, 10분 넘게 멈춘 finalizing은 running으로 회수.
- G6 다운로드·전송(🟡3): 입력 사진은 본문(base64 등)으로 보내고 서명 URL을 외부에 넘기지 않는다. 결과는 어댑터 상수 허용 호스트(https)만, 리다이렉트는 허용 호스트로만 최대 3회, DNS가 사설·루프백·링크로컬이면 거부, 스트리밍 바이트 상한 200MB, mp4 `ftyp` 시그니처 확인. Storage 서버 업로드 함수를 storage.py에 추가.
- G7 권한(사람 결정 대신 팀장 기본값, 바꿀 수 있음): 견적·목록·검수 = 구성원, **확인(과금) = owner만**. 요청자 본인 검수 허용(소규모 내부 팀). 예산 설정 UI 없음(SQL로 설정, 기본 0).
- G8 쓰기 허용 확장: `apps/api/app/production/videogen/**`, `apps/api/app/routes/production_generation.py`(+라우터 등록 1줄), `apps/api/app/production/shopping.py`(assets_map reviewed만), `apps/api/app/production/storage.py`(서버 업로드 함수), `apps/api/app/config.py`(VIDEOGEN_*), `supabase/migrations/20261120000026_generation_runs.sql`, `supabase/tests/`, `docs/04_API.md`(A-22)·`docs/05_DATA_MODEL.md`(82·83행), `.env.example`(이름만), 테스트. 웹 UI는 task-057.
- G9 완료 조건 추가: 동시 확인 2건 중 예산 내 1건만, 중복 refresh 1건만 완료, 리다이렉트·사설 IP·비허용 호스트 거부, 0원·null 예산 거부, owner 아닌 확인 403, 기본 꺼짐 503.

## 구현 결정 (builder 2026-11-20)
- 상태에 `finalizing`(완료 처리 선점, G5)을 추가했고, 계상 여부는 `billable` 칼럼으로 둔다(확인 때 true, 명확한 4xx 거부·입력 사진 읽기 실패로 미제출이면 false).
- 견적도 예산을 확인한다(0원·초과면 run 기록 없이 409). 확인 RPC는 owner 확인 → workspace·job·run 잠금 → 상태·사진·예산 재계산 순서다. 확인 오류 409 본문은 `{code: CONFLICT, field: budget_exceeded, remaining_krw}`.
- 견적 대상은 `kind=shopping` 작업만, 입력 사진은 ready `image`·basis `own`·`licensed`·인물이면 초상 동의(가정).
- 결과 자산 권리 = 입력 사진 rights(gen·reviewed 키 제외) + `basis: ai_generated` + `gen{platform, model, request_id, cost_krw=coalesce(actual, est)}`. created_by = 확인한 owner.
- xAI 어댑터의 엔드포인트·요청/응답 모양·모델 이름·초당 단가(USD 0.08)·결과 호스트(`vidgen.x.ai`)는 가정이다(실제 호출·약관 확인은 사람 할 일). 환율 `VIDEOGEN_KRW_PER_USD` 기본 1450(가정).
- DNS 검사 뒤 연결 시점 재해석(DNS rebinding)은 막지 못한다(허용 호스트로 범위를 줄임). 결과는 최대 200MB를 메모리에 받은 뒤 Storage에 올린다.
- 리뷰 반영 1: 작업 삭제 시 run은 남고 job_id만 null(비용·멱등 키 보존, 월 집계 유지). 삭제된 작업의 run 완료는 result_rejected.
- 리뷰 반영 2: 확인 후 5분 넘게 request_id 없는 confirmed는 재확인·refresh 때 unknown(`submit_stalled`, 계상 유지, 재제출 없음). running 기록 RPC 실패는 1회 재시도, 그래도 실패면 run id·request_id sha256 앞 16자만 로그.
- 리뷰 반영 3: finish 호출이 예외면 run을 재조회해 done·같은 result_asset_id면 객체 유지(재조회 실패도 유지 — 고아 객체 쪽을 택함).
- 리뷰 반영 4: claim이 `finalize_token`(uuid)을 발급하고 finish(성공·실패 모두)가 토큰 일치를 조건으로 한다. 회수 시 토큰 null.
- 리뷰 반영 5: 플랫폼 보고 비용(원)이 견적×10 또는 int4를 넘으면 actual=None(견적으로 계상)·로그, 업로드 전에 계산.
