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

## 구현 결정 (2026-11-20, builder)
- 마이그레이션 `20261120000023_shopping_api.sql`: `parent_asset_id`+(parent, job_id) 복합 FK·kind check·부모 source_upload 트리거(23514), `one_ready_source_uidx` → `production_assets_source_limit` 트리거(일반 ready 2건째·쇼핑 11건째 23505, ready 전환은 draft·failed(prepare)만 NR010), ready 원본 삭제 가드(NR010), finish(000020 본문+쇼핑 원본별 한 벌 검사 NR012), claim(000021 본문+새 수령에서 shopping 제외). pgTAP `production_shopping_api_test.sql` 22건.
- 일반 ready 원본 중복도 23505라 기존 `production_api_test.sql` 단정을 그대로 통과. **`production_shopping_test.sql` 56번(쇼핑 prepare claim → job_kind shopping)은 P4와 충돌해 실패 — 쓰기 허용 밖이라 수정하지 않음(팀장 확인).**
- 계보(P1): 쇼핑 W-07은 parent 필수, 일반 업로드 작업은 생략 시 그 작업의 ready 원본으로 채움(기존 워커 호환), URL 작업·render는 parent 400. 승인 자산 맵은 `shopping.assets_map`(파생 source의 rights=부모, source_upload의 duration=파생 source, reviewed=False 고정, width·height 없음 → 1080x1920 가정).
- 금지 품목(P7): 확인 체크 `not_banned_confirmed`(A-09 입력, 저장 안 함) + 키워드(제목·brief·comment_keyword를 NFKC·casefold·문자·숫자만 → 부분 일치). 오류는 400 VALIDATION field `banned_category`. A-11 준비 시작·PATCH에서도 재검사. "약" 같은 짧은 단어는 오탐 때문에 넣지 않음(키워드 목록은 가정).
- brief 모델: product_name·pain(상품)·destination·product_type(stay·tour·package)·appeal(여행)·scenes ≤5·avoid·facts ≤10·target{gender, age}, 분야 외 항목 400. 장면 3개 최소·필수 항목은 화면 검사(API는 초안 저장 허용).
- 제휴 링크: DB check가 https만이라 API도 https만(task 본문 "http(s)"와 다름), 사용자 정보·공백 거부, 2048자·20건.
- 업로드: 쇼핑 image·bgm·narration 추가(mime: jpeg·png·webp / 음성은 hook_audio 목록). 쇼핑은 rights 필수, 일반은 선택. `has_person`+동의 없음 400. source_upload·image 각 10건, **narration은 문장별 녹음 4건(사용자 결정 2026-11-20) — 같은 kind pending 일괄 삭제를 건너뛰고 상한에 pending 포함**, bgm·hook_audio는 이전 pending 삭제. image·bgm·narration 상태는 draft·review·inspect·failed(가정). spec의 narration_asset_ids 4개 형식은 task-045.
- 자산 삭제(P9): DELETE 204, 행 먼저 삭제 후 객체(실패는 로그만). hook_audio·워커 산출물은 409.
- A-21: 출력 `{text{caption, pinned_comment, recommended_time}, render_run_id, lang}`, 링크는 pinned_comment에만. 대가성 문구·권장 시각 문구는 가정.
- 목록 `lang` 필터·`langs[]`는 `current_revision_id`·`current_ja_revision_id` 유무로 계산(추가 조회 없음).
- 쇼핑 preset_version `shopping-1080-v1`(가정, 045와 맞출 것). W-09 finish asset_ids 상한 10×202, 자산 조회는 100건씩 나눔.

## 리뷰 반영 결정 (2026-11-20, code·security 🔴 없음, 000023 미커밋이라 직접 수정)
- 1 `production_shopping_test.sql` 56번: 쇼핑 prepare claim 결과 null(미배정)로 기대값 변경. 000023의 준비 시작 트리거 때문에 같은 블록에 ready 원본 1건 insert를 함께 추가했다(설정 줄).
- 2 A-11: kind=shopping은 금지 품목 재검사 뒤 409(field `kind`, "쇼핑 렌더러 준비 중입니다.") — task-045에서 해제. (04_API A-11 행은 쓰기 허용 밖이라 미반영.)
- 3 `production_jobs_prepare_source` 트리거: status가 preparing으로 바뀌고 source_kind=upload면 ready source_upload ≥1(없으면 NR010 → API 409 field `source_upload`). 원본 삭제 가드와 같은 job 행 잠금으로 직렬화.
- 4 `production_assets_source_limit`를 source_upload·image·narration으로 넓힘: 쇼핑은 job 행 잠금 뒤 kind별 개수(pending 포함) 원본 10·사진 10·녹음 4, 넘으면 23505 → 409.
- 5 `shopping.no_control`: 유니코드 범주 Cc·Cf·Zl·Zp 거부(U+2028·2029·0085·bidi·폭 없는 문자). brief·partner·rights·comment_keyword(Keyword)에 적용. 제목(Title)은 기존 규칙 그대로.
- 6 `production_assets_ref_delete_guard` 트리거: image·bgm·narration 삭제 때 job 행 잠금 뒤 현재 리비전(ko·ja)의 cuts·bgm_asset_id·voice.narration_asset_id(·045의 narration_asset_ids) 참조 시 NR010 → 409. A-12 저장·A-13 승인 RPC와 같은 job 잠금으로 직렬화하고, 저장 직전 삭제 경합은 승인 재검증(cuts.source_invalid 등)이 막는다. A-15 렌더 요청의 자산 재확인은 `production_render.py`가 쓰기 허용 밖이라 하지 않았다.
- 7 PATCH: 쇼핑 항목(brief·affiliates·vertical·comment_keyword)만 보내면 review·inspect에서도 허용, 다른 필드가 섞이면 기존 draft·failed(prepare) 규칙.
- pgTAP: production_shopping_api_test 29건(+7). pytest 1149 통과.
