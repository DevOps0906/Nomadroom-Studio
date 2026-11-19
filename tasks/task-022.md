# task-022 제작 작업 API A-09~A-13·A-17·A-18

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-020, task-021 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(업로드·서명 URL 발급 · 인증 후 POST/PATCH/PUT) · 경로 보안 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-09`~`#A-13`·`#A-17`·`#A-18`, `docs/05_DATA_MODEL.md#storage`, `docs/01_PRD.md#8` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/storage.py`, `apps/api/app/main.py`(라우터 등록만), `apps/api/tests/production/test_jobs_api.py`, `apps/web/src/server/api/production.ts`(호출 함수만) |

## 할 것
- A-09 POST·PATCH·GET(멱등 키·권리 확인·구간 검증), A-10 업로드 서명 PUT·완료(15분·크기 확인), A-11 prepare, A-12 리비전 GET·PUT(낙관적 잠금·오류 있어도 저장), A-13 승인(서버 재검증), A-17 검수 승인, A-18 다운로드 서명 GET(10분).
- A-09 candidate_id는 같은 워크스페이스 후보인지 API가 확인한다(DB FK는 소속을 보장하지 않음, task-020 구현 결정). 업로드 크기 상한 500MB(Q8 확정). A-12 저장 시 `validate_spec`에 source_duration·job_lang을 넘기고, source_start_sec·preset_version 작업 값 비교를 추가한다. 04 A-12에 "스키마 오류 시 의미 검사 미실행"을 적는다(task-021 리뷰 🟡2·4). 권리 확인 시 rights_confirmed_by·at을 반드시 함께 저장한다(task-020 리뷰 🟡4).
- A-09는 `format`을 받아 저장한다. W4 동안 `variety`는 400 `VALIDATION`("준비 중"), task-035에서 연다(`tasks/plan-variety-shorts.md` D-V1).
- 웹·API는 작업 ID·자산 ID만 주고받는다. 타 워크스페이스 404.

## 하지 않을 것
- 렌더 요청·재시도·워커 API(023), AI 초안·URL 다운로드(P1), 서명 URL 로그 출력, 화면.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_jobs_api.py` 통과(멱등 재요청 200, 409 상태 불가, 타 워크스페이스 404, 오류 있는 spec 승인 400, 경로 필드 거부)
- [ ] `cd apps/api && pytest -q` 전체 회귀 통과 · 로그 캡처에 서명 URL 토큰 0건

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- 쓰기 허용 추가: `supabase/migrations/*000016*.sql`(새 파일) · `supabase/tests/*production*`(pgTAP) · `docs/04_API.md`(A-09~A-18 정정만).
- D1 멱등: 000016에 `production_jobs.idempotency_key text not null` + `unique(workspace_id, idempotency_key)`. 같은 키 재요청은 본문이 달라도 기존 job 200(A-07 규칙). unique 위반 → 재조회 패턴(verify_runs.py·collect_jobs.py).
- D2 원자성: A-12 PUT(리비전 insert·current_revision_id·inspect/failed→review)과 A-13 승인은 security definer RPC(service_role 전용 execute)로 각각 한 트랜잭션. A-12 미승인 행 덮어쓰기는 `approved_at is null` 조건, A-13은 재검증 때 읽은 updated_at 조건 → 불일치 409.
- D3 A-12 허용 상태: review·inspect·failed(failed_stage∈{audio,render})만. 리비전 없음·그 외 상태 409.
- D4 업로드 서명 만료: Supabase `/object/upload/sign`은 만료 지정 불가(기본 2시간)면 실측값을 응답 `expires_at`으로 내보내고 04 A-10을 실제 값으로 고친다(비공개 버킷·경로 고정·upsert 끔으로 위험 수용). 다운로드 A-18은 expiresIn 600.
- D5 A-10: source_upload는 draft·failed(prepare)에서만, 작업당 1건(새 요청 시 이전 pending 삭제, ready 있으면 409). hook_audio는 review·failed(render)에서만, narration·variety면 400. complete는 Storage 실제 크기 = 선언값 ≤ 524288000, 이미 ready면 200.
- D6 source_kind=url은 W4 동안 400 VALIDATION("준비 중")(SSRF는 task-031).
- D7 권리 확인: false→true일 때만 by=현재 사용자·at=now, true 재전송 유지, false면 둘 다 null. 클라이언트 by·at은 extra=forbid로 거부.
- D8 A-11: 조건부 PATCH 한 번(draft 또는 failed+prepare, retry_count<3)으로 status·retry_count 갱신, failed_stage·error_code·claimed_by null. 0행 409.
- D9 자산 조회는 항상 id·job_id·workspace_id 세 조건, 불일치 404. A-17은 현재 승인 리비전의 최신 done run mp4_asset_id가 ready인지 확인.

## 구현 결정 (builder 보고)
- D4 실측(2026-11-19, 로컬 Supabase CLI 3.1.0): `/object/upload/sign` 토큰 exp−iat = **7200초**, 본문 `expiresIn`·헤더로도 바뀌지 않음. 같은 URL 두 번째 PUT은 400(덮어쓰기 끔). A-10 `expires_at`은 토큰 exp로 계산하고 04 A-10·공통 문구를 2시간으로 고쳤다. 다운로드 `/object/sign`은 expiresIn 600 그대로(exp−iat=600). 객체 크기는 `/object/info/production/{path}`의 `size`, 없으면 400.
- 마이그레이션 000016: `idempotency_key`(기존 행은 id로 채운 뒤 not null)·`production_jobs_workspace_id_idempotency_key_key`, RPC `save_production_revision`·`approve_production_revision`(security definer, service_role만 실행, job 행 `for update`로 직렬화). SQLSTATE NR009=404, NR010=409 상태, NR011=409 잠금 불일치.
- A-12 PUT: 스키마 오류(`schema.*`)·`path.forbidden`은 저장하지 않고 400(`errors[]`·`warnings[]` 동봉), 그 밖 의미 오류는 저장. 작업 값 비교 코드 `source_start_sec.mismatch`(허용 오차 0.001)·`preset_version.mismatch`는 spec에 값이 있을 때만. `source_duration`은 최신 ready `source` 자산 `duration_sec`(없으면 None).
- A-13: 재검증 오류면 400 + 목록, RPC는 재검증 때 읽은 리비전 updated_at 일치 시만 승인하고 재검증 결과(warnings)를 validation에 저장.
- 응답은 `{job}`·`{revision}`·`{asset}`로 감싼다(A-05와 같은 방식). 409 상태 불가는 `message`에 현재 status. 상세 `job`에서 `claimed_by`·`idempotency_key` 제외. 서명 URL 응답에 `Cache-Control: no-store`.
- `preset_version` category 값은 `category-1080-v1`(가정). A-09 `source_start_sec` 상한 86400초(가정). `kind`·`vertical` 등 쇼핑 필드는 extra=forbid로 400(task-042).
- 상세 `worker_online`은 수집과 같은 계산(run·job의 claimed_by 워커, 없으면 워크스페이스 워커 heartbeat 최댓값 3분).
- 검증: api pytest 614(test_jobs_api 51) · pgTAP 345(production_api_test 34, production_rls_test에 키 추가) · 로컬 실 Supabase 스모크(생성·멱등·업로드 PUT·완료·prepare·저장·승인·다운로드) 통과(scratchpad, 미커밋).

## 리뷰 반영 결정 (reviewer 🟡, 2026-11-19)
- 🟡1 A-09 PATCH·A-17 검수 승인도 `production_jobs.updated_at`=now를 기록한다(A-11·A-12와 같게).
- 🟡2 hook_audio 업로드 요청도 같은 작업의 이전 pending hook_audio를 객체+행째 지운다(ready는 유지).
- 🟡3 complete 크기 불일치 시 Storage 객체와 pending 행을 지우고 409(`size_bytes`) 유지 → 업로드 요청부터 다시.
- 🟡4 동시 complete 경합: 000016(커밋·원격 적용 전이라 수정)에 부분 unique `production_assets_one_ready_source_uidx`(job_id) where kind='source_upload' and status='ready'. 위반은 API 409, pgTAP 1건.
- 🟡5 위험 수용: 지운 pending의 업로드 토큰은 최대 2시간 살아 있어 그 사이 PUT하면 행 없는 고아 객체가 남을 수 있다(비공개 버킷·서명 URL 없이는 접근 불가, 용량만 차지). 정리 배치(행 없는 객체 삭제)는 후보로만 두고 Q5 보관·삭제 작업 때 함께 검토.
- 🟡6 04 A-09 GET의 `kind`·`lang`·`shopping` 필터와 `kind`·`vertical`·`langs[]` 칼럼에 "W4 미구현(task-042·049)" 표시.
- 🟡7 웹 `ApiError`가 400 응답의 `errors[]`·`warnings[]`를 버린다: client.ts는 범위 밖이라 그대로 두고, task-025/026에서 ApiError에 errors를 보존한다.
- 🟡8 확인: `_send`는 `service_headers`(service_role 키)로 PostgREST·RPC를 부른다. 버킷 `file_size_limit`=524288000·`allowed_mime_types`는 000015에 있다.
- 검증: api pytest 618(test_jobs_api 55) · pgTAP 346(production_api_test 35).
