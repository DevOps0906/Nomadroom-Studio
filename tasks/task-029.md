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
