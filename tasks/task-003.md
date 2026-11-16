# task-003 FastAPI 뼈대 · JWT 검증 · 워커 토큰 인증

| 항목 | 내용 |
|---|---|
| 웨이브 | W1 |
| 선행 | task-001, task-002 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 · 키·권한 (JWT·워커 토큰·service_role) |
| 담당 | builder |
| 근거 | `docs/04_API.md#공통 규칙·#보안 메모`, `docs/02_ARCHITECTURE.md#2`, `docs/01_PRD.md#8`, `docs/adr/0001-worker-location.md`, `.claude/rules/api.md` |
| 쓰기 허용 | `apps/api/**`, `.env.example` |

## 할 것
- `apps/api` FastAPI · Pydantic v2 뼈대, `/healthz`, 공통 오류 형식 `{code,message,field?}`.
- 사용자 의존성: Supabase JWT 서명·만료 검증 + `workspace_members` 소속 확인 → `workspace_id` 결정(입력으로 안 받음).
- 워커 의존성: `Authorization: Bearer` 토큰 → `workers.token_hash` 비교, `revoked_at` 폐기 시 401. 토큰 발급·폐기 CLI 스크립트(운영 절차).
- 로깅 필터: 키·JWT·토큰·쿠키 마스킹. service_role은 서버 환경변수로만.

## 하지 않을 것
- 비즈니스 엔드포인트(A-02~A-08, W-01~W-04), LLM 호출, 토큰 원문 저장.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q` 통과: 무토큰·만료·타 워크스페이스·폐기 토큰 401/403/404 케이스
- [ ] 로그 캡처 테스트에 토큰 문자열 0건
- [ ] `~/.claude/nomad/bin/secscan license` GPL·AGPL 0건
