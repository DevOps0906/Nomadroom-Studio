# task-034 예능형 편집안 검증 모듈

| 항목 | 내용 |
|---|---|
| 웨이브 | W6 |
| 선행 | task-021, task-028 |
| 위험도 | 보통 |
| 보안 영향 | 없음(순수 검증 함수) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md#예능형-spec`, `tasks/plan-variety-shorts.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/api/app/production/validation_variety.py`, `apps/api/app/production/validation.py`(format 분기 진입점만), `apps/api/tests/production/test_validation_variety.py` |

## 할 것
- variety spec Pydantic 모델: header(1~2줄)·cuts(src 범위·0.2초 오류·0.5초 경고·배율 1~3·띠 빈 화면 2축 검사·1~60개·총길이 상한)·subtitles(line/punch·겹침 오류·공백 허용·1.4초 경고)·reactions(캔버스 안·겹침 경고).
- 오류·경고를 `{code, path, message}`로 반환. 경로·URL 필드 거부. format 값으로 카테고리형/예능형 모듈 분기.

## 하지 않을 것
- 카테고리형 검증 규칙 변경, API 라우트, 렌더러.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_validation_variety.py` 통과(예제 컷 14개 spec 통과, 빈 화면·범위 초과·자막 겹침·0.2초 미만 오류, 0.5초·1.4초 경고)
- [ ] `cd apps/api && pytest -q tests/production` 카테고리형 검증 회귀 통과
