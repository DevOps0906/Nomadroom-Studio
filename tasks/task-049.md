# task-049 일본어판 파생·번역 A-20

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-047 |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(Claude) · 텍스트 외부 전송 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md` A-20, `docs/05_DATA_MODEL.md`(lang·derived_from), `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/translate*.py`, 테스트 |

## 할 것
- 승인된 ko 리비전 → ja 리비전 파생(컷·구도·마스크 고정 복사), Claude 구어체 번역 초안(형식별 텍스트 필드만), ko 변경 시 재파생 경고.

## 하지 않을 것
- 원본 영상·음성 전송, ja에서 컷 수정 허용.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q tests/production` 통과(파생 후 텍스트 외 필드 동일, 번역 모의 응답)
