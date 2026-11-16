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
- [x] `cd apps/api && pytest -q` 통과: 무토큰·만료·타 워크스페이스·폐기 토큰 401/403/404 케이스
- [x] 로그 캡처 테스트에 토큰 문자열 0건
- [x] `~/.claude/nomad/bin/secscan license` GPL·AGPL 0건

## 구현 결정 (팀장, 2026-11-16 · challenger 검토 반영)
- JWT: 로컬 CLI 3.1.0 JWKS 확인 결과 ES256(EC P-256, kid 있음). **JWKS 비대칭만** 허용(alg 허용 목록 ES256·RS256, 알고리즘은 JWK의 kty·alg로 고정, 헤더 alg 불신). HS256·레거시 JWT secret 경로 없음(API에 그 비밀을 두지 않는다).
- 검증 항목: 서명·exp·aud=`authenticated`·iss=설정값 `SUPABASE_JWT_ISSUER`(기본 `{SUPABASE_URL}/auth/v1`)·sub(UUID) 필수. role=`authenticated`만.
- JWKS: httpx 비동기 조회, 메모리 캐시 TTL 10분. 모르는 kid는 재조회하되 60초에 최대 1회. 조회 실패·키 없음 = 503 `UPSTREAM_ERROR`(서버 쪽 문제), 서명·클레임 실패 = 401.
- 소속: service_role로 PostgREST 조회. 0행 = 403 `FORBIDDEN`, 2행 이상 = 403(MVP는 1개, 다중 워크스페이스 이후). limit 1로 고르지 않는다.
- service 키: 새 형식 `sb_secret_`는 `apikey` 헤더로만 보낸다. JWT 형식(레거시)이면 `apikey`+`Authorization: Bearer`로 보낸다. 환경변수 `SUPABASE_SERVICE_ROLE_KEY`.
- 워커 토큰: `<worker_id>.<secret>`(secrets.token_urlsafe(32)), DB에는 sha256(secret) hex 저장, PK로 조회한 뒤 compare_digest로 비교. 형식 오류·UUID 아님·없음·해시 불일치·revoked는 모두 같은 401 `UNAUTHENTICATED`. worker_id는 UUID로 파싱한 뒤에만 쿼리에 넣는다.
- CLI: `issue --workspace --name`(새 행) · `rotate --id`(같은 행 token_hash 교체, heartbeat·jobs 연결 유지) · `revoke --id`(revoked_at). 토큰 원문은 stdout에 1회만 출력하고 로그에 남기지 않는다.
- 오류 형식: 422→400 `VALIDATION`(field만, `input` 값은 응답·로그 금지). Starlette 404·405, 처리 안 된 500도 `{code,message}`로 변환. 메시지에 내부 경로·예외 원문 금지.
- 로그 마스킹: **루트 핸들러**에 필터를 붙이고 포매팅이 끝난 문자열(traceback 포함)을 대상으로 한다. 패턴: `Bearer \S+`, JWT(`eyJ…\.…\.…`), `sb_(secret|publishable)_\S+`, 워커 토큰(`<uuid>\.[A-Za-z0-9_-]{20,}`), apikey·cookie 헤더 값. 테스트: 워커 토큰 원문·JWT·service 키가 들어간 예외(traceback 포함)를 uvicorn.error·httpx·app logger로 찍어 원문 0건 확인.
- 403·404 증명: 테스트 안에서 `create_app()`에 테스트 전용 라우트를 붙인다(운영 코드에 테스트 라우트 없음). 404 헬퍼 `not_found_if_other_workspace()`를 제공하고 단위 테스트한다.
- 테스트 케이스: 무토큰·만료·alg none·공개키로 서명한 HS256·모르는 kid·aud 없음·다른 iss·sub 누락·비소속(403)·다중 소속(403)·타 워크스페이스 리소스(404)·워커 토큰 형식 오류·폐기·해시 불일치. + **통합 1건**: 로컬 `supabase start` 실제 토큰(admin API로 테스트 사용자 생성·로그인) → 200. 통합 테스트는 `-m integration`, 키는 `npx supabase@3.1.0 status -o env`를 셸 환경변수로만 쓰고 파일에 쓰지 않는다.
- 세션 철회: JWT는 exp(최대 3600초)까지 유효하다. 소속은 매 요청 확인하므로 소속 제거는 즉시 반영된다. 로그아웃 세션의 즉시 차단은 하지 않는다(팀장 결정, 내부 도구).
- 의존성: fastapi·uvicorn·pydantic-settings·pyjwt[crypto]·httpx(+ dev: pytest·pytest-asyncio 또는 anyio·respx). uv 프로젝트, Python은 최신 stable(uv 관리), 버전은 pyproject와 README에 적는다.
