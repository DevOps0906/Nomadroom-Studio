# task-005 판정 엔진

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-003 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | builder + tester |
| 근거 | `docs/01_PRD.md#9`, `docs/05_DATA_MODEL.md#candidate_verdicts·observations`, `docs/02_ARCHITECTURE.md#3-2` |
| 쓰기 허용 | `apps/api/app/verdict/**`, `apps/api/tests/verdict/**` |

## 할 것
- 순수 함수 `judge(profile, candidate, prev_obs, curr_obs)` → status·reason·growth_pct (PRD#9 순서 1~3, reason 코드 그대로).
- 대표 판정 `pick_representative(verdicts, used)`: 제작 가능 > 근거 대기 > 첫 프로필, `used`가 우선.
- 증가율·관측 간격(24시간~7일) 계산, 방송사는 목록 포함 여부(미확인 없음), 라이선스만 미확인 허용.

## 하지 않을 것
- DB·네트워크 접근, 새 판정 규칙·수치 추가.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/verdict` 통과: PRD#9 표 행마다 1케이스 이상(경계 0·허용 증가율 포함)
- [ ] reason 코드 전수(`market`·`category`·`format`·`views_min`·`not_cc`·`broadcaster`·`keyword`·`no_prev`·`license_unknown`·`growth_out_of_range`)가 테스트에 등장
