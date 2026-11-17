# task-021 편집안 검증 모듈

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-003 |
| 위험도 | 보통 |
| 보안 영향 | 없음(경로 필드 거부는 검증 규칙으로 포함) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md#편집안-spec-필드`, `docs/research/category-shorts-ref/`(render.py·check.py `validate()`), `tasks/plan-category-shorts.md` 팀장 설계 결정 |
| 쓰기 허용 | `apps/api/app/production/spec.py`, `apps/api/app/production/__init__.py`, `apps/api/tests/production/test_spec.py` |

## 할 것
- Pydantic v2 편집안 스키마 + 검증 함수: 오류(공백·겹침·범위 초과·빈 화면 배율·Y·NaN·제목 2줄·첫 자막 0초 아님·items.y 범위·자막 공백) / 경고(1.4초 미만). 반환은 `{errors[], warnings[]}`.
- 자막 kind는 `white`·`paren`·`emph`. 절대 경로·`..`·URL 문자열 필드 거부.
- 배포본 `validate()` 동등성: 같은 입력 픽스처로 결과 일치.

## 하지 않을 것
- 훅 길이(`hook_too_long`)·폭 초과(`text_too_long`) 서버 검사(렌더 워커 몫), DB·라우트 연결.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_spec.py` 통과(오류 항목별 1건 이상, 경고는 오류 0일 때도 반환, 배포본 픽스처 동등)
- [ ] 경고만 있는 spec은 `errors == []`
