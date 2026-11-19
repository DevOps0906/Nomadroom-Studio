# task-023 렌더 요청·재시도 A-15·A-16 + 워커 API W-05~W-09

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-022 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(워커 토큰 API·서명 URL 발급) · 동시성(멱등·원자적 수령) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-15`·`#A-16`·`#W-05`~`#W-09`, `docs/02b_PRODUCTION_FLOW.md`(상태·오프라인), `docs/adr/0003-production-render-worker.md` |
| 쓰기 허용 | `apps/api/app/routes/production_render.py`, `apps/api/app/routes/worker_production.py`, `apps/api/app/production/runs.py`, `apps/api/app/main.py`(라우터 등록만), `apps/api/tests/production/test_render_runs.py`, `apps/api/tests/production/test_worker_production.py`, `docs/04_API.md`(W-09 `제안` 표기 정리만) |

## 할 것
- A-15 렌더 요청(멱등 키·(작업, 리비전, 언어) 1건·동시 1건), A-16 재시도(완료 파일 덮어쓰기 없음).
- W-05 수령(조건부 갱신·워커당 1건·재시작 복구), W-06 입력 서명 GET, W-07 산출물 서명 PUT(kind 허용 목록), W-08 진행·오프라인 평가, W-09 완료·실패(`hook_too_long`·`text_too_long`은 review 복귀, `worker_offline`은 서버 생성).
- 훅 공식 정본은 `docs/04_API.md#W-09` 그대로 구현.

## 하지 않을 것
- 워커 본체(024), DB 직접 접속 경로, 수집 워커 W-01~W-04 변경, P1 `source_url` 전달.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_render_runs.py tests/production/test_worker_production.py` 통과(동시 2건째 409, 멱등 재요청, 두 워커 동시 claim 중 1건만 수령, 허용 외 kind 400, 타 워크스페이스 토큰 404)
- [ ] `cd apps/api && pytest -q` 전체 회귀 통과

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- 쓰기 허용 추가: `supabase/migrations/*000017*.sql`(새 파일) · `supabase/tests/*production*` · `apps/api/app/routes/production_jobs.py`(A-09 GET 만료 호출·A-10 hook_audio 허용 상태만) · `docs/04_API.md`(A-15·A-16·W-05~W-09 정정).
- E1 원자성: A-15·A-16·W-05(prepare·render 수령)·W-09·오프라인 만료는 job 행 `for update` security definer RPC(service_role 전용) 한 트랜잭션. SQLSTATE→404/409 매핑은 022(NR009~011) 방식을 잇는다.
- E2 수령: RPC에서 `order by created_at limit 1 for update skip locked`로 1건. 자기 running run·자기 preparing job이 있으면 그것을 먼저 돌려준다(재시작 복구). 수령 시 updated_at(run은 started_at·updated_at)=now.
- E3 오프라인: running/preparing은 max(updated_at, 수령 시각)에서 3분(04 정본 값) 지나면 worker_offline. queued run이 10분 동안 수령되지 않으면 failed(worker_offline) — 워크스페이스 렌더 영구 잠금 방지. 취소 API는 만들지 않는다. 평가 시점: W-05·W-08·A-09 GET·A-15·A-16.
- E4 하트비트: W-05·W-08에서 worker_heartbeats upsert, current_job_id는 null(jobs FK).
- E5 A-16: job failed·failed_stage∈{audio,render}·run.revision_id=current_revision_id·(job,리비전,언어) 최신 run만. attempt=체인 최댓값+1, 상한 3. hook_too_long·text_too_long run은 거부(A-15 안내).
- E6 W-09 입력: error_stage·error_code는 kind별 Literal, worker_offline 거부. asset_ids는 같은 job·pending·허용 kind·created_by=워커·render_run_id=run(prepare는 null)만. 목록에 없는 해당 run의 pending 산출물은 지운다.
- E7 W-07: task당 pending 상한(sheet 수+10), kind→mime·확장자 서버 허용 목록(버킷 allowed_mime과 일치), 만료는 실측 2시간으로 04 정정.
- E8 A-15 lang=ja는 400 VALIDATION("준비 중")(task-049 전까지). 멱등 키로 찾은 run의 job_id가 경로와 다르면 409.
- E9 W-06 입력: 최신 ready source·analysis + render_run_id null인 최신 ready hook_audio(variety·narration은 없음).
- E10 audio_missing 복구: A-10 hook_audio를 failed(audio)에서도 허용(재승인 없이 A-16 재시도).
- E11 검증: pgTAP(RPC 동시 수령·active 유니크 409·만료) + 로컬 Supabase 스모크(claim 2회 → 1건)를 완료 조건에 추가.

## 구현 결정 (builder 보고, 2026-11-19)
- 마이그레이션 000017(함수만, 테이블 변경 없음 → ERD·타입 재생성 불필요): `expire_production_offline`·`request_render_run`·`retry_render_run`·`claim_production_task`·`finish_production_task`(+ 응답 모양 `_render_run_json`), 모두 security definer·service_role만 실행. 잠금 순서 job → run(만료 RPC는 대상 job을 id 순으로 먼저 잠금). SQLSTATE: NR009 404 · NR010 409(문구에 현재 상태) · NR011 409 다른 작업의 멱등 키 · NR012 400(리비전·산출물 목록) · NR013 429 · NR014 409 진행·완료 렌더 · NR015 409 재시도 상한. 매핑은 `app/production/runs.py`.
- A-15 판정 순서: 멱등 키(상태 무관 200) → review → 현재 승인 리비전(아니면 400) → 진행·완료 run 409 → 60초 내 새 키 429 → insert(부분 unique 경합은 NR014). "동시 2건째 409"가 429에 가려지지 않게 409를 먼저 본다. `revision_id`는 job의 현재 리비전만 허용.
- A-16: 서버 키 `retry:{run_id}`, attempt ≤ 3(최초 1 + 재시도 2)으로 해석. job `failed(audio·render)`만.
- W-05: 자기 running run → 자기 preparing job → 대기 task(preparing 미수령 job과 queued run 중 created_at 오래된 것) 순. 재시작 복구 때도 updated_at=now. 미수령 preparing job은 만료하지 않는다(워크스페이스 잠금이 없어 E3 범위 밖).
- W-07: kind→mime 허용(source·output_mp4=mp4, analysis·report=json, sheet=jpg, hook_audio=A-10과 같음), task당 pending ≤210·sheet ≤200, 응답에 `expires_at`(실측 2시간). 서명은 항목마다 순차 호출.
- W-09: 크기 확인은 API(Storage `object/info`)가 RPC 전에, 목록 재확인·ready·pending 삭제·전이는 RPC. 지운 pending의 Storage 객체는 RPC 뒤 API가 지우고 실패해도 응답은 성공(고아 객체는 task-022 🟡5와 같은 위험 수용). render done은 mp4·report 정확히 1건, hook_audio ≤1. prepare done의 첫 리비전은 빈 spec `{}` + 서버 검증 결과(스키마 오류 목록), `meta`는 `source_meta`. 실패면 이 task의 pending 산출물을 모두 지운다. `hook_too_long`·`text_too_long`은 job `review`(failed_stage·error_code null, 사유는 run.error_code), 그 밖은 job `failed(error_stage)`.
- 만료로 실패한 run의 pending 산출물은 그대로 남는다(행·객체, 위 고아와 같은 위험 수용 — Q5 정리 배치 후보).
- A-09 GET(목록·상세)에서 만료 평가. 기존 `tests/production/test_jobs_api.py`는 만료 RPC 목 1줄 추가·E10으로 failed(audio) hook_audio 기대값 409→201 수정(범위 밖 파일, 필수 수정).
- 검증: api pytest 686(test_render_runs 23 · test_worker_production 45) · pgTAP 382(production_render_test 36) · 로컬 스모크(동시 claim 5회 모두 200+204, prepare→render→inspect 실 Storage PUT·GET, 다른 워커 409, API 로그 서명 토큰 0건) 통과(scratchpad, 미커밋).

## 리뷰 반영 결정 (code·security 리뷰, 🔴 없음, 2026-11-19)
- 1 prepare done: `source`·`analysis` 정확히 1건, `sheet` 1건 이상(API 400·RPC NR012 둘 다). RPC 안 23505는 `runs.py`에서 409 CONFLICT로 매핑(503 누수 방지).
- 2 prepare done은 `meta` 필수(API 400), SQL은 `source_meta = coalesce(p_meta, source_meta)`. 04 W-09 반영.
- 3 복구 수령: 새 수령과 같은 갱신 문(prepare `updated_at`, render `started_at`·`updated_at`)을 지나므로 이미 now()였다. 주석과 pgTAP·pytest로 확인을 고정.
- 4 만료 RPC는 jsonb `{expired, deleted_paths}`를 돌려준다. 만료 run(render_run_id)·만료 preparing job(prepare 산출물)의 pending 행을 지우고, API가 Storage 객체를 지운다(실패는 무시, 로그에는 자산 id만). 경로를 잃지 않게 A-15·A-16·W-05 RPC 안의 만료 호출을 빼고 API가 RPC 앞에서 부른다(만료와 판정 사이 짧은 틈은 409로 끝나 수용).
- 5 W-07 kind별 크기 상한: sheet 5MB · analysis·report 50MB · source·output_mp4·hook_audio 500MB. 04 W-07 반영.
- 6 A-16: `coalesce(error_code, '')`·`coalesce(failed_stage, '')`로 null이 거부 조건을 우회하지 않게.
- 7 04 W-09: finish 재호출 409 = 이미 처리됨으로 해석.
- 검증: `supabase db reset` 후 pgTAP 389(production_render_test 43) · api pytest 전체(신규 리뷰 테스트 각 항목 1건 이상).
