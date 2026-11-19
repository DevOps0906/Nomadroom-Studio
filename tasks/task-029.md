# task-029 AI 초안 A-14 (Claude)

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 |
| 선행 | task-028 |
| 위험도 | 높음 |
| 보안 영향 | 새 의존성(Anthropic SDK) · 키(LLM 키는 FastAPI에만) · 노출 면(외부 LLM 전송 범위) · 비신뢰 입력(프롬프트 주입) · 비용 상한 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-14`, `docs/01_PRD.md#8`, `docs/01_PRD.md#7`(Q7), `docs/05_DATA_MODEL.md#편집안-spec-필드` |
| 쓰기 허용 | `apps/api/app/production/ai_draft.py`, `apps/api/app/routes/production_ai.py`, `apps/api/app/config.py`(키 이름 추가만), `apps/api/app/main.py`(라우터 등록만), `apps/api/pyproject.toml`·lock(의존성 추가만), `apps/api/tests/production/test_ai_draft.py`, `.env.example`(이름만), `apps/web/src/components/production/edit/AiDraftButton.tsx`, `apps/web/src/app/api/production-jobs/[id]/ai-draft/**` |

## 할 것
- A-14: 0.5초 시트 JPEG·analysis.json·후보 제목만 Claude에 전송, 구조화 JSON을 spec 스키마로 검증, 새 리비전(`origin=ai_draft`), 기존 편집 덮어쓰기 없음.
- 작업당 호출 상한(Q7 확정값, 성공·실패 모두 기록), 스키마 불일치 시 재시도 1회, 입력 텍스트는 데이터로만 취급.
- PROD-02 "AI 초안" 버튼.

## 하지 않을 것
- 원본 영상·음성 전송, 키의 웹·워커·로그 노출, 초안 자동 승인, 상한 미확정 상태로 배포.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_ai_draft.py` 통과(Claude는 목: 전송 페이로드에 영상·음성 0건, 상한 초과 429, 스키마 불일치 502, 사용자 편집 보존)
- [ ] `~/.claude/nomad/bin/secscan license` 통과(GPL·AGPL 0건) · lockfile 갱신 · `grep -rn "sk-ant" apps` 0건
- [ ] `pnpm typecheck && pnpm test` 통과

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- 쓰기 허용 추가: `supabase/migrations/*000018*.sql`(새 파일) · `supabase/tests/*production*` · `apps/web/src/components/production/edit/edit-form.tsx`·`edit/api.ts`(버튼 연결만) · `apps/web/src/server/api/production.ts`(타입·호출 함수만) · `docs/04_API.md`(A-14 정정).
- H1 Q7 확정: 작업당 3회(01_PRD#7). 성공·실패 모두 계수. A-20 번역 호출은 이 상한에 넣지 않는다(task-049에서 별도).
- H2 000018 RPC: `reserve_ai_draft`(job 행 잠금·review 확인·count<3·+1·멱등 키 기록, 커밋 후 Claude 호출 — 잠금을 쥔 채 호출 금지) · `create_ai_draft_revision`(행 잠금·review 확인·항상 새 rev_no·origin='ai_draft'·current_revision_id 이동). revoke/grant는 000016과 같게. 같은 키 재요청은 기존 결과 200, 횟수 증가 없음. 같은 작업 60초 내 새 키는 429 RATE_LIMITED.
- H3 format≠category면 409, Claude 미호출(variety는 task-040).
- H4 서버 값 필드(lang·source_start_sec·preset_version·hook.audio_asset_id·hook.tts)는 AI 출력에서 버리고 작업·직전 리비전 값으로 덮어쓴다. 검증은 기존 `_validate` 재사용, 스키마 불일치 시 1회 재시도 후 502.
- H5 설정값(하드코딩 금지): 모델 기본 `claude-sonnet-5-5`, 시트 장수 상한 16, max_tokens, items·shots 개수 상한, SDK 타임아웃. 공식 Anthropic Python SDK 사용(MIT, secscan 확인). claude-api 스킬을 먼저 읽는다.
- H6 502 본문은 고정 문구, SDK 예외·응답 원문 로그 금지, 키 없으면 503(앱 기동은 정상).
- H7 테스트는 SDK `messages.create` 인자를 가로채 이미지가 image/jpeg 시트뿐이고 source·mp4 자산 0건임을 단언, 실제 네트워크 차단(사용자 결정: 목 전용).
- H8 미저장 변경이 있으면 AI 초안 전에 확인. 응답에 직전 rev_no를 담고 화면에 "이전 편집안 rev N은 보관됨" 안내(되돌리기 UI는 후속, README 발견한 문제).
- 순서: task-032(edit-form.tsx 수정 중) 커밋 뒤 착수. 마이그레이션 번호 000018=029, 000019=031.

## 구현 결정 (2026-11-19, builder)
- 멱등 키 기록: 새 테이블 대신 `production_jobs.ai_draft_requests`(jsonb 배열, 원소 `{key, status(pending·done·failed), base_rev_no, revision_id, requested_by, created_at, finished_at}`) 칼럼. 새 테이블은 `supabase/tests/rls_test.sql`의 테이블 수 단언(쓰기 범위 밖)을 깨고 ERD·타입 재생성이 필요해서 피했다. 작업당 최대 3건이라 크기 문제 없음. 다른 작업에 쓴 키는 같은 워크스페이스 작업들의 배열 포함 검사로 409(NR011). 서로 다른 두 작업이 같은 키로 동시에 요청하는 경합은 막지 않는다(키는 클릭마다 UUID라 수용).
- RPC(000018): `reserve_ai_draft(p_workspace, p_job, p_user, p_key, p_limit)` · `create_ai_draft_revision(…, p_key, p_spec, p_validation)` · `fail_ai_draft(p_workspace, p_job, p_key)`(void). SQLSTATE 추가: NR016 상한 → 429 `QUOTA_EXCEEDED`, NR017 60초 내 새 키 → 429 `RATE_LIMITED`, NR018 같은 키 처리 중(pending) → 409. 판정 순서: 같은 키 재요청(기존 결과, 상태·상한 무관) → 다른 작업 키 409 → review 아님 409 → format≠category 409 → 상한 429 → 60초 429. 상한 값은 API 설정 `ai_draft_max_per_job`(기본 3)을 인자로 넘긴다.
- 횟수는 요청(멱등 키) 단위: 스키마 불일치 재시도 1회는 같은 요청 안이라 추가 계수 없음. 예약 뒤 입력 수집(Storage) 실패·Claude 실패·리비전 생성 거부(호출 중 상태 변경 등)는 모두 `fail_ai_draft`로 failed 기록, 횟수는 그대로 소진. 실패한 키의 재요청은 같은 502(기존 결과), "다시 시도"는 새 키(60초 간격 적용).
- 응답: 새 리비전 201, 같은 키 재요청 200. 본문 `{revision, ai_draft_count, previous_rev_no}`(`previous_rev_no`=예약 시점 현재 rev_no, H8).
- Claude 호출: 공식 Anthropic Python SDK `anthropic` 2.10.0(Apache-2.0 — H5의 "MIT"와 다름, 허용 라이선스. 새 전이 의존성 httpx2·httpcore2 BSD-3, jiter·docstring-parser·truststore·h11 MIT, opentelemetry-api Apache-2.0), `AsyncAnthropic(max_retries=0, timeout=설정)`, `messages.create`에 도구 하나(`submit_edit_draft`, JSON 스키마)와 `tool_choice` 강제로 구조화 출력. 도구 스키마에는 편집 필드(header·hook.text·duration·shots·items)만 두고, 서버가 lang·source_start_sec·preset_version과 직전 리비전 hook.audio_asset_id·tts를 채운다(AI가 보낸 값은 버림). overlays(P1)는 초안 대상 아님.
- 전송: ready `sheet` 자산 중 mime `image/jpeg`이고 내용이 JPEG 매직(FFD8FF)인 것만, 생성 순 상한 `ai_draft_max_sheets`장, 장당 5MB 이하. Storage는 서비스 키로 `object/authenticated` GET(서명 URL을 만들지 않음). analysis.json은 압축 JSON 문자열로 넣고 20만 자 넘으면 자름. 후보 제목·analysis는 `<untrusted_data>` 블록 안 JSON 문자열로만, 꺾쇠는 `<`·`>`로 이스케이프해 블록을 닫지 못하게 했다. 원본·hook_audio·mp4 객체는 읽지도 않는다.
- 새 환경변수 이름(값은 `.env`에만, `.env.example`은 팀장이 추가): `ANTHROPIC_API_KEY`(없거나 공백이면 A-14만 503), `AI_DRAFT_MODEL`(기본 `claude-sonnet-5-5`), `AI_DRAFT_MAX_PER_JOB`(3), `AI_DRAFT_MAX_SHEETS`(16), `AI_DRAFT_MAX_TOKENS`(8192), `AI_DRAFT_MAX_ITEMS`(80), `AI_DRAFT_MAX_SHOTS`(40), `AI_DRAFT_TIMEOUT_SEC`(90).
- 로그: `AI 초안 생성: job rev count errors`·`AI 초안 실패: job reason=<예외 이름·코드>`만. 키·프롬프트·응답 원문·SDK 예외 메시지 없음.
- 웹: `AiDraftButton`("AI 초안 채우기", 실패 후 "AI 초안 다시 시도", 클릭마다 새 키 `ai-<uuid>`). 미저장 변경이 있으면 confirm. 성공 시 새 리비전을 양식에 반영하고 "AI 초안 rev N을 만들었습니다. 이전 편집안 rev M은 보관됨" 안내. 버튼은 job `review`일 때만 활성. edit-form.tsx 변경은 import·phase `drafting`·`applyDraft`·버튼 한 줄·빈 상태 안내 문구뿐.
