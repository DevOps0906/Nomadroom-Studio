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
- [x] `cd apps/api && pytest -q tests/verdict` 통과: PRD#9 표 행마다 1케이스 이상(경계 0·허용 증가율 포함)
- [x] reason 코드 전수(`market`·`category`·`format`·`views_min`·`not_cc`·`broadcaster`·`keyword`·`no_prev`·`license_unknown`·`growth_out_of_range`)가 테스트에 등장

## 구현 결정 (팀장, 2026-11-16 — 문서에 없는 해석)
- 단위: `max_growth_pct`·`growth_pct`는 %(0.6 = 0.6%). growth_pct = (curr−prev)/prev×100, 소수 둘째 자리 반올림(Decimal). 판정 비교는 반올림 전 값으로.
- 관측 간격: prev는 curr와의 간격이 24시간 이상 7일 이하(양 끝 포함, PRD#9)일 때만 유효. 범위 밖이면 이전 관측 없음으로 보아 `no_prev`.
- prev.view_count = 0이면 증가율 계산 불가 → 조건 제외 `growth_out_of_range`, growth_pct null.
- 조건 없음: `category` null, `keywords` 빈 배열, `format`=`all`은 해당 조건을 통과.
- 키워드: 후보 제목에 키워드 중 **하나 이상** 포함(OR). 대소문자 무시, NFKC 정규화 후 부분 문자열 비교.
- 순서 1 안의 조건 확인 순서와 reason 우선은 PRD#9 표의 위쪽 행 순서(market → category → format → views_min → not_cc → broadcaster → keyword). 순서 2 안은 `no_prev` > `license_unknown`.
- 제작 가능이면 reason = null(시드와 동일).
- 대표 판정: 입력 verdicts 순서가 프로필 순서(position). used=true면 대표 상태와 관계없이 `used` 표시 우선(반환에 used 플래그 포함, rep_status는 판정 결과대로 계산).
- 입력은 dataclass/Pydantic 모델(DB 행과 같은 필드 이름). 시각은 timezone-aware datetime만 허용.
- 라이선스 판정은 `candidates.license_cc`(API가 최신 관측으로 갱신하는 값)를 쓴다. 프로필이 category·format을 지정했는데 후보 값이 null이면 불일치(조건 제외).
- 표시 메모: 비교는 반올림 전 값이라 -0.003%·5.004%처럼 경계 근처에서 제외된 후보의 growth_pct가 0.00·5.00으로 보일 수 있다. 화면(MON-D2)은 reason 문구를 우선 표시한다.
