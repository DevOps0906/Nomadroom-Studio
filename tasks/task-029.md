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
