# task-051 예능형 일본어 더빙

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-050, task-038 |
| 위험도 | 높음 |
| 보안 영향 | TTS 의존 · 난이도 |
| 담당 | builder + tester |
| 근거 | `tasks/plan-shopping-japanese.md#팀장 설계 결정`(예능형 더빙) |
| 쓰기 허용 | `apps/worker/production/variety/**`(dub), 테스트 |

## 할 것
- 대사 자막별 ja TTS → 자막 구간 배치, 원본 duck(가정 15%), 넘치면 rate↑(상한 가정 +30%) 후 `dub_overflow` 경고.

## 하지 않을 것
- 원본 음성 완전 삭제 강제, 입모양 맞춤.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q tests/production/test_variety_dub.py` 통과(구간 안 배치·overflow 경고)
