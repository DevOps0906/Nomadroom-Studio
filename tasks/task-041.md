# task-041 예능형 P1 인수 테스트 VAR-06·07 + 회귀

| 항목 | 내용 |
|---|---|
| 웨이브 | W7 |
| 선행 | task-040 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | tester |
| 근거 | `tasks/plan-variety-shorts.md#인수 기준`, `docs/01_PRD.md#2`(S12) |
| 쓰기 허용 | `apps/**/tests/production/acceptance/**`, `apps/web/src/**/*.test.ts(x)`(제작 화면만), `tasks/NOW.md` |

## 할 것
- VAR-06·07과 카테고리형 CAT 회귀.

## 하지 않을 것
- 제품 코드 수정.

## 완료 조건 (실행 가능한 확인)
- [ ] api·worker `pytest -q tests/production` · `pnpm test` 통과
- [ ] VAR-06·07 결과 `NOW.md` 기록
