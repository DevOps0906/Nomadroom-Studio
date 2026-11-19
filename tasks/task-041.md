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

## 구현 결정 (2026-11-20, tester)
- 추가: `apps/api/tests/production/acceptance/test_var_p1_acceptance.py`(7, 가짜 PostgREST·목 Claude, 실서버·db reset 없음). 웹·워커는 기존 variety·CAT 테스트 재실행으로 회귀(새 파일 없음).
- VAR-06 대체표: task-039 보류로 받아쓰기(transcribe) 시나리오 없음 -> (a) 수동 대사->AI 초안->사용자 수정 저장 (b) 대사 없음·수동 입력만 (c) AI 실패 502 후 수동 저장. 렌더는 VAR-01·03(038)이 덮음.
- VAR-07: 검증 통과 · 컷이 구간 끝에 정확히 닿는 경계 · 오류 경로(cuts.1) · 스키마 위반 502 리비전 미생성.
- 참고: `transcribe_state` 컬럼은 job 응답에 남아 있으나 받아쓰기 라우트는 없음(보류).
