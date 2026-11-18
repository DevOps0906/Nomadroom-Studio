# task-040 예능형 AI 초안

| 항목 | 내용 |
|---|---|
| 웨이브 | W7 |
| 선행 | task-039, task-029 |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(Claude) · 대사 텍스트 외부 전송(01#8) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-14`, `docs/01_PRD.md#8`, `docs/05_DATA_MODEL.md#예능형-spec` |
| 쓰기 허용 | `apps/api/app/production/ai_draft*.py`, `apps/api/tests/production/test_ai_draft_variety.py` |

## 할 것
- A-14 format 분기: 입력 transcript 텍스트·저해상도 시트·후보 제목, 출력 variety spec(구조화 JSON) → 서버 검증 후 새 리비전(origin=ai_draft). 호출 상한 Q7 공용.

## 하지 않을 것
- 원본 영상·음성 전송, 키를 웹·워커에 두기, 검증 우회 저장.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_ai_draft_variety.py` 통과(Claude 응답 모의: 정상·스키마 위반·상한 초과)
