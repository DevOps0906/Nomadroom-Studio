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
- [x] `cd apps/api && pytest -q tests/production/test_spec.py` 통과(오류 항목별 1건 이상, 경고는 오류 0일 때도 반환, 배포본 픽스처 동등)
- [x] 경고만 있는 spec은 `errors == []`

## 구현 결정 (builder 보고, 팀장 수용)
- 진입점: `app/production/spec.py`의 `validate_spec(raw, *, source_duration=None, job_lang=None) -> {errors, warnings}`. 스키마 오류(`schema.<type>`)가 나면 의미 검사를 건너뛴다(배포본 validate도 첫 오류에서 멈춤, 의도).
- 오류 코드: `shots.*`·`items.*`·`duration.range`·`header.lines.invalid`·`hook.text.empty`·`hook.audio_xor`·`lang.mismatch`·`path.forbidden`·`overlays.*`. 경고는 `items.too_short`이며 오류가 있어도 함께 반환한다.
- 경로·URL 거부는 자산 ID·코드 성격 필드에만 적용한다. 자막·제목 문구는 검사하지 않는다. 나머지 필드는 `extra=forbid`로 막는다.

## 리뷰 반영 결정 (reviewer code ACCEPT, 🟡 후속)
- 🟡1 동등성 테스트 강화(오류 코드 비교, hook 빈 값·NaN·헤더 줄 수·items y 케이스, 원본 줄 번호 주석): task-028 인수 테스트에서 보강한다.
- 🟡2 `source_start_sec`·`preset_version` 작업 값 비교: task-022 저장 흐름(A-12)에서 작업 값을 넘겨 검사한다.
- 🟡3 overlays·자막 겹침 경고(P1): task-032.
- 🟡4 "스키마 오류 시 의미 검사 미실행"을 04 A-12에 한 줄로 적는다: task-022에서 반영한다.
