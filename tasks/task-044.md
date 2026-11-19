# task-044 쇼핑 API

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-043 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(다건 업로드·제휴 링크 입력) · 입력 검증 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md` A-09·A-10·A-11·쇼핑 항목, `docs/02b_PRODUCTION_FLOW.md` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/**`, `apps/api/tests/production/**` |

## 할 것
- A-09 kind·vertical·brief·affiliates, 의약품·건기식 400. 원본 다건 업로드·자산별 권리 입력, 원본별 prepare(전부 끝나야 review). 제휴 링크 http(s)만·길이 상한. 업로드 kind `image`·`bgm`·`narration`(권리 basis 필수). **A-21 게시 문구**(쇼핑만), A-09 목록 kind·vertical·langs[]·상세 언어별 current_revision.

## 하지 않을 것
- 렌더러·화면·AI, 제휴 링크 자동 발급·외부 호출.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production` 통과(금지 품목 400, 다건 prepare 상태, 권리 없는 승인 400)
- [ ] 로그에 제휴 링크·서명 URL 토큰 0건

## 착수 결정 (2026-11-20, challenger 검토 반영 · 팀장 결정)
- 순서: task-040(마이그레이션 000022) 커밋 뒤 착수. 마이그레이션 `20261120000023_shopping_api.sql`, reserve_ai_draft는 건드리지 않는다.
- 쓰기 허용 추가: `apps/api/app/routes/worker_production.py` · `apps/api/app/main.py`(A-21 라우터 등록만) · `supabase/migrations/20261120000023_shopping_api.sql` · `supabase/tests/production_shopping_api_test.sql` · `apps/web/src/types/db.ts`·`docs/diagrams/erd.mmd`(재생성만) · `docs/04_API.md`(A-09·A-10·A-21·W-05·W-06·W-07).
- P1 계보: `production_assets.parent_asset_id` + (parent_asset_id, job_id)→(id, job_id) 복합 FK. W-07은 원본 파생 산출물(source·analysis·sheet)에 parent 필수. 승인 때 assets 맵의 rights·reviewed는 부모 source_upload(사용자 입력) 값, duration은 파생 source 값.
- P2 원본 개수: one_ready_source_uidx를 지우고 트리거로 대체 — job 행 FOR UPDATE 후 general은 ready 1건, shopping은 pending 포함 10건 이하, job.status ∈ (draft, failed(prepare))일 때만 ready 전환. 위반은 SQLSTATE→409.
- P3 finish(shopping prepare): ready source_upload 전부가 각각 source·analysis 정확히 1건(+sheet ≥1)을 가져야 review, 아니면 NR012.
- P4 TaskOut.job_kind Literal에 shopping 추가 + 재현 테스트. 단 **task-045(쇼핑 렌더러) 전까지 claim은 kind=shopping job을 내주지 않는다**(현재 워커는 원본 1건만 처리) — 045에서 해제.
- P5 업로드: shopping의 source_upload·image는 같은 kind pending 일괄 삭제를 건너뛰고 상한에 pending 포함. W-07 상한은 shopping이면 원본 수×(sheet 200+2).
- P6 권리 입력: RightsIn extra=forbid, gen·reviewed 필드 받지 않음, 사용자 업로드에 basis ai_generated 거부(AI 생성 자산은 054 경로만). reviewed는 사용자 jsonb에서 읽지 않는다.
- P7 금지 품목(의약품·건기식): NFKC·casefold·공백 제거 후 키워드 검사, 우회 사례 테스트.
- P8 A-21 게시 문구: render_run을 job_id·workspace·status done·lang 조건으로 필터, 로그에 제휴 링크·서명 토큰 0(caplog로 400·500 경로까지).
- P9 자산 삭제 API(팀장 결정): DELETE `/production-jobs/{id}/assets/{asset_id}` — source_upload는 draft·failed(prepare)에서만, image·bgm·narration은 현재 리비전이 참조하지 않을 때만. 객체+행 삭제.
- P10 PATCH 허용 필드에 brief·affiliates·vertical 추가(kind 불변). W-06 쇼핑 렌더 입력 확장은 task-045.
