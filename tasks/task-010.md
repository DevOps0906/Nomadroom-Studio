# task-010 프로필 API A-03

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-003 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (인증 후 수정 API, 입력 검증) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-03`, `docs/05_DATA_MODEL.md#profiles`, `docs/01_PRD.md#8` |
| 쓰기 허용 | `apps/api/app/routes/profiles.py`, `apps/api/tests/profiles/**` |

## 할 것
- `GET /v1/profiles`, `PUT /v1/profiles/{id}`(범위 검증, 동시 수정 `updated_at` 불일치 409), `PUT /v1/profiles/selection`(최대 3, 없는 id 400).
- market은 KR·JP만 허용.

## 하지 않을 것
- 프로필 생성·삭제(이후), 저장된 보기, 웹 화면.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/profiles` 통과: min_views<0·max_growth_pct 1001·키워드 6개·selection 4개 → 400, 409, 타 워크스페이스 404
