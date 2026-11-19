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

## 구현 결정
- 진입점은 `validation.py`를 새로 만들지 않고 `apps/api/app/production/validation_variety.py`의 `validate_for_format(format, spec, ...)`에 둔다. `category`는 `spec.validate_spec`을 그대로 호출(카테고리형 코드 변경 없음), `variety`는 `validate_variety_spec`, 그 밖은 `format.unknown`.
- 오류·경고는 task-021과 같은 `{code, path, message}`. 스키마 위반은 `schema.<pydantic type>`, 경로·URL은 알 수 없는 필드면 `schema.extra_forbidden`, `preset_version`이 경로 모양이면 `path.forbidden`.
- 빈 화면: 원본 폭을 1080에 맞춘 상태가 배율 1. 원본 크기를 모르면 1080x1920(세로)로 가정하고, 호출 쪽이 `source_size=(폭, 높이)`를 넘기면 그것을 쓴다. x·y는 px(띠 중심 540,968 기준).
- `segment_len`이 없으면 `cuts.out_of_range`의 상한 검사만 생략한다. 컷 총길이·자막·반응 범위는 컷 길이 합계를 기준으로 한다.
- 예제 컷 14개 중 컷 2(0.43초)는 W `cuts.short`가 정상이다.
- 상수(0.2·0.5·1.4·60·180)는 Q11 가정값이며 모듈 상단 상수 한 곳에서 바꾼다.
- 예능형은 W6 동안 ko 전용이다(일본어 더빙은 task-051). `source_start_sec`·`preset_version`의 작업 값 비교는 호출부(task-035) 담당이다.
