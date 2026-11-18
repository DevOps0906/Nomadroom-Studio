# task-047 쇼핑 P0 인수 SHOP-01~06

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-045, task-046 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | tester |
| 근거 | `tasks/plan-shopping-japanese.md#인수 기준` |
| 쓰기 허용 | `apps/**/tests/production/acceptance/**`, `tasks/NOW.md` |

## 할 것
- SHOP-01~06 시나리오(원본은 저장소 밖 합성·자체 촬영 샘플).

## 하지 않을 것
- 제품 코드 수정, 타인 영상 커밋.

## 완료 조건 (실행 가능한 확인)
- [ ] api·worker `pytest -q tests/production` 통과
- [ ] SHOP-01~06 표를 NOW.md에 기록
