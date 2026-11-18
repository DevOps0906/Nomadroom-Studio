# task-038 예능형 P0 인수 테스트 VAR-01~05

| 항목 | 내용 |
|---|---|
| 웨이브 | W6 |
| 선행 | task-036, task-037 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | tester |
| 근거 | `tasks/plan-variety-shorts.md#인수 기준`, `docs/01_PRD.md#2`(S11) |
| 쓰기 허용 | `apps/api/tests/production/acceptance/**`, `apps/worker/tests/production/acceptance/**`, `tasks/NOW.md` |

## 할 것
- VAR-01~05 시나리오. 실습 원본·완성본은 저장소 밖 경로(환경변수)로만 사용하고 예제 컷 14개를 재현 렌더.
- VAR-01 재현 규칙: 예제 컷 3(원본 속도 0.95)은 속도 1.0으로 하고 원본 길이 = 출력 길이 1.37초로 입력한다(컷별 속도는 미지원). 카테고리형 회귀는 P1 변경 뒤 task-041에서 다시 한다(VAR-05와 시점이 다름).

## 하지 않을 것
- 제품 코드 수정(실패는 보고만), 원본 영상 커밋.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production` · `cd apps/worker && pytest -q tests/production` 통과
- [ ] VAR-01~05 통과 표를 `NOW.md`에 기록
