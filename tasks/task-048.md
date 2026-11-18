# task-048 AI 대본 3안 + 게시 문구 초안

| 항목 | 내용 |
|---|---|
| 웨이브 | W9 |
| 선행 | task-047, task-029 |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(Claude) · brief 텍스트 외부 전송 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md` A-14·A-21, `docs/research/shopping-shorts-notion-analysis.md#3` |
| 쓰기 허용 | `apps/api/app/production/ai_*.py`, `apps/api/tests/production/test_ai_shopping.py` |

## 할 것
- 노션 프롬프트 규칙으로 후킹이 다른 3안·글자 수·후킹 유형·확인할 사실 목록. 게시 문구 초안(대가성 표기 첫 줄·댓글 키워드). 출력은 서버 검증 후 저장. 호출 상한 Q7 공용.

## 하지 않을 것
- 확인 안 된 효능·가격 생성 허용, 키를 웹·워커에 두기.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q tests/production/test_ai_shopping.py` 통과(모의 응답: 정상·[확인 필요]·스키마 위반)
