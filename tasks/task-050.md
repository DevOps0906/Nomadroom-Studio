# task-050 일본어 TTS·렌더

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-049, task-030 |
| 위험도 | 높음 |
| 보안 영향 | 새 자산(JP 글꼴 OFL) · TTS 의존 |
| 담당 | builder + tester |
| 근거 | `docs/research/category-shorts-zip-analysis.md#3`(일본어 규격), `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/worker/production/**`(lang 분기), `apps/worker/production/fonts/**`, 테스트 |

## 할 것
- 카테고리형 ja 훅 TTS·쇼핑 ja 내레이션, Noto Sans CJK JP, ja 표기 "PR", (작업, 리비전, ja) 별도 MP4.

## 하지 않을 것
- 무음 대체, 라이선스 미확인 글꼴.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/worker && pytest -q tests/production` 통과(ja 렌더 2형식)
