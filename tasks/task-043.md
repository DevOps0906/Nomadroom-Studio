# task-043 쇼핑 편집안 검증

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-042 |
| 위험도 | 보통 |
| 보안 영향 | 없음(순수 검증) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md` 쇼핑 spec 표, `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/api/app/production/validation_shopping.py`, `validation.py`(분기만), `apps/api/tests/production/test_validation_shopping.py` |

## 할 것
- script 정확히 4문장(오류)·110~140자(경고)·`[확인 필요]`(오류)·금지 문구·1번 제품명(경고). cuts 다중 원본·문장 매핑(문장마다 1개 이상)·masks 범위·빈 화면. voice 둘 중 하나(narration은 kind `narration`만). `image` 컷·`motion`(pan·zoom·none, `cuts.motion_invalid`), AI 생성 컷 미검수 `gen.unreviewed`. 권리 승인 조건(basis 전부·초상 동의).

## 하지 않을 것
- 일반쇼츠 검증 변경, 렌더러.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_validation_shopping.py` 통과
- [ ] `pytest -q tests/production` 회귀 통과
