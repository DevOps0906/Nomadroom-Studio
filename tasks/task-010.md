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
- [x] `cd apps/api && pytest -q tests/profiles` 통과: min_views<0·max_growth_pct 1001·키워드 6개·selection 4개 → 400, 409, 타 워크스페이스 404

## 구현 결정 (팀장, 2026-11-16 · challenger 검토 반영)
- PUT /{id} 입력 필드(정확히): market·format·category·min_views·max_growth_pct·keywords·cc_only·include_broadcast·updated_at. **name·selected는 받지 않는다**(extra=forbid → 400). 선택은 /selection만.
- 낙관적 잠금: PATCH 조건 `id=eq&workspace_id=eq&updated_at=eq.<요청값>`, 본문에 `updated_at = 서버 UTC now`(마이크로초). 0행이면 workspace_id로 한정해 다시 조회 → 없으면 404, 있으면 409. 응답에 새 updated_at. updated_at은 timezone 있는 ISO 8601만 허용(naive는 400), 서버가 받은 문자열을 httpx params로 인코딩. 테스트: 같은 토큰으로 PUT 2회 → 두 번째 409, 마이크로초 값, 타 워크스페이스 id + 틀린 updated_at → 404.
- 범위: min_views 0~2,000,000,000 int, max_growth_pct 0~1000(Decimal, 소수 둘째 자리까지), keywords 0~5개, 각 항목 앞뒤 공백 제거 후 1~30자, 대소문자 무시 중복 제거, 빈 문자열은 400. category: 앞뒤 공백 제거 후 ≤40자, 빈 문자열·`전체`는 null. market KR·JP, format all·short·long.
- selection: **원자적 RPC** `public.set_profile_selection(p_workspace uuid, p_ids uuid[])` (새 마이그레이션 파일). 한 트랜잭션에서 해당 워크스페이스 profiles를 `for update`로 잠근 뒤 ids가 모두 그 워크스페이스에 있는지 확인(아니면 예외 → API 400 "없는 id", 타 워크스페이스도 같은 400), 3개 초과 예외, selected 갱신. updated_at은 바꾸지 않음(편집 폼 409 방지). security invoker, `set search_path=''`, execute는 service_role만 grant. 빈 배열 허용(전부 해제). 중복 id는 제거.
- PostgREST 오류: 4xx·5xx 모두 503 `UPSTREAM_ERROR`, 메시지는 "데이터 저장소 요청에 실패했습니다"(인증 문구와 분리). RPC의 비즈니스 예외(SQLSTATE 지정)만 400으로 매핑.
- 쓰기 허용 확장: `apps/api/app/main.py`(router include 한 줄), `apps/api/app/errors.py`(DB 오류 문구 추가), `supabase/migrations/20261116000006_profile_selection_rpc.sql`, `supabase/tests/**`(RPC pgTAP), `docs/04_API.md` A-03 행(팀장).
