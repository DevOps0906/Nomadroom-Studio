# task-033 P1 인수 테스트 CAT-08 + 회귀

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 |
| 선행 | task-029, task-030, task-031, task-032 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | tester |
| 근거 | `docs/01_PRD.md#2`(S10), `Nomadroom_Category_Shorts_PRD.md#5`(CAT-08), `docs/02b_PRODUCTION_FLOW.md` |
| 쓰기 허용 | `apps/api/tests/production/acceptance/**`, `apps/worker/tests/production/acceptance/**`, `apps/web/src/**/*.test.ts(x)`(제작 화면 테스트만), `tasks/NOW.md` |

## 할 것
- CAT-08(P1 통합: AI 초안·TTS·URL 원본·오버레이 포함 1건 종단)과 P0 CAT-01~07 회귀. TTS 실패 시 첨부 음성 복귀 경로 확인.

## 하지 않을 것
- 제품 코드 수정(실패는 보고만), P2·후속 범위.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q` · `cd apps/worker && pytest -q` · `pnpm typecheck && pnpm lint && pnpm test` 전체 통과
- [ ] 종단 산출물 `ffprobe` 608×1080·30fps·h264/aac
- [ ] `supabase test db` 통과 · CAT-01~08 통과 표를 `NOW.md`에 기록
